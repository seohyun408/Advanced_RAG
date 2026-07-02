"""SQS 롱폴링 워커. ECS 컨테이너의 백그라운드 스레드로 실행된다.

큐에서 job_id를 받아 run_assistant를 실행하고 결과를 DynamoDB에 저장한 뒤
메시지를 삭제한다. run_assistant가 예외를 던져도 claim_and_store가 error로
기록하므로 메시지는 항상 삭제된다(무한 재처리 방지).
"""

import threading

from app import jobs
from app.supervisor import run_assistant


def process_message(receipt_handle: str, job_id: str) -> None:
    user_input = jobs.get_user_input(job_id)
    if user_input is None:
        # 레코드가 만료/삭제됨 — 메시지만 정리
        jobs._get_sqs().delete_message(QueueUrl=jobs.QUEUE_URL, ReceiptHandle=receipt_handle)
        return
    jobs.claim_and_store(job_id, runner=lambda: run_assistant(user_input))
    jobs._get_sqs().delete_message(QueueUrl=jobs.QUEUE_URL, ReceiptHandle=receipt_handle)


def _poll_loop() -> None:
    sqs = jobs._get_sqs()
    while True:
        try:
            resp = sqs.receive_message(
                QueueUrl=jobs.QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,  # 롱폴링
            )
        except Exception:  # noqa: BLE001 — 일시 오류 시 루프 유지
            continue
        for msg in resp.get("Messages", []):
            try:
                process_message(msg["ReceiptHandle"], msg["Body"])
            except Exception:  # noqa: BLE001 — 개별 메시지 실패가 루프를 죽이지 않도록
                pass


def start_worker() -> None:
    if not jobs.QUEUE_URL:
        return  # 큐 미설정 환경(로컬 테스트 등)에서는 워커 비활성
    threading.Thread(target=_poll_loop, daemon=True).start()
