"""완전일치 질문 캐시 (DynamoDB).

같은 질문(공백/대소문자만 다른 경우 포함)이 반복되면 LLM을 다시 부르지 않고
저장된 답변을 재사용한다. TTL로 24시간 뒤 자동 만료된다.
"""

import hashlib
import os
import time
from typing import Optional

import boto3

REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
CACHE_TABLE_NAME = os.environ.get("CACHE_TABLE_NAME", "realestate-cache")
_CACHE_TTL_SECONDS = 86400  # 24시간

_table = None


def _get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb", region_name=REGION).Table(CACHE_TABLE_NAME)
    return _table


def _normalize(question: str) -> str:
    return question.strip().lower()


def _hash(question: str) -> str:
    return hashlib.sha256(_normalize(question).encode("utf-8")).hexdigest()


def get_cached(question: str) -> Optional[dict]:
    resp = _get_table().get_item(Key={"question_hash": _hash(question)})
    item = resp.get("Item")
    if not item:
        return None
    return {"output": item["output"], "route": item["route"]}


def store_cached(question: str, output: str, route: list) -> None:
    now = int(time.time())
    _get_table().put_item(
        Item={
            "question_hash": _hash(question),
            "output": output,
            "route": route,
            "created_at": now,
            "expires_at": now + _CACHE_TTL_SECONDS,
        }
    )
