"""SQS(작업 큐) + DynamoDB(결과 저장소) 기반 job 저장소.

- submit_job: DynamoDB에 queued 레코드 write + SQS에 job_id 발행 (실행 안 함)
- 워커(app/worker.py)가 SQS를 폴링해 claim_and_store로 실행/결과 기록
- get_job: DynamoDB 조회 (프론트 polling 대상)
"""

import os
import time
import uuid
from typing import Callable, Optional

import boto3

from app import cache

REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
QUEUE_URL = os.environ.get("JOB_QUEUE_URL", "")
TABLE_NAME = os.environ.get("JOB_TABLE_NAME", "realestate-jobs")
_JOB_TTL_SECONDS = 3600

_sqs = None
_table = None


def _get_sqs():
    global _sqs
    if _sqs is None:
        _sqs = boto3.client("sqs", region_name=REGION)
    return _sqs


def _get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    return _table


def submit_job(user_input: str) -> str:
    """DynamoDB에 queued 레코드를 쓰고 SQS에 job_id를 발행. 즉시 job_id 반환.

    완전일치 캐시에 같은 질문의 답변이 있으면 큐를 거치지 않고 done으로 기록한다.
    """
    job_id = uuid.uuid4().hex
    now = int(time.time())

    hit = cache.get_cached(user_input)
    if hit is not None:
        _get_table().put_item(
            Item={
                "job_id": job_id,
                "status": "done",
                "user_input": user_input,
                "output": hit["output"],
                "route": hit["route"],
                "created_at": now,
                "expires_at": now + _JOB_TTL_SECONDS,
            }
        )
        return job_id

    _get_table().put_item(
        Item={
            "job_id": job_id,
            "status": "queued",
            "user_input": user_input,
            "created_at": now,
            "expires_at": now + _JOB_TTL_SECONDS,
        }
    )
    _get_sqs().send_message(QueueUrl=QUEUE_URL, MessageBody=job_id)
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    resp = _get_table().get_item(Key={"job_id": job_id})
    item = resp.get("Item")
    if not item:
        return None
    result = {"status": item["status"]}
    for key in ("output", "route", "error"):
        if key in item:
            result[key] = item[key]
    return result


def get_user_input(job_id: str) -> Optional[str]:
    """워커가 큐에서 받은 job_id로 원본 질문을 조회."""
    resp = _get_table().get_item(Key={"job_id": job_id})
    item = resp.get("Item")
    return item.get("user_input") if item else None


def mark_running(job_id: str) -> None:
    _update(job_id, {"status": "running"})


def store_result(job_id: str, output: str, route: list) -> None:
    _update(job_id, {"status": "done", "output": output, "route": route})


def store_error(job_id: str, message: str) -> None:
    _update(job_id, {"status": "error", "error": message})


def claim_and_store(job_id: str, runner: Callable[[], dict], user_input: Optional[str] = None) -> None:
    """워커가 호출: runner() 실행 결과/오류를 DynamoDB에 기록.

    user_input이 주어지고 성공하면 완전일치 캐시에도 결과를 저장한다.
    """
    mark_running(job_id)
    try:
        result = runner()
        output, route = result["output"], result["route_history"]
        store_result(job_id, output, route)
        if user_input is not None:
            cache.store_cached(user_input, output, route)
    except Exception as e:  # noqa: BLE001 — job 단위 격리
        store_error(job_id, f"{type(e).__name__}: {e}")


def _update(job_id: str, fields: dict) -> None:
    names = {f"#{k}": k for k in fields}
    values = {f":{k}": v for k, v in fields.items()}
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in fields)
    _get_table().update_item(
        Key={"job_id": job_id},
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )
