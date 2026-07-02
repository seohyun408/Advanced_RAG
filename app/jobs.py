"""인메모리 job 저장소.

SQS 전환 시 submit_job(제출)과 get_job(조회) 내부만 교체한다:
submit → SQS SendMessage, get → 결과 저장소(DynamoDB 등) 조회.
"""

import threading
import time
import uuid
from typing import Callable, Optional

_JOB_TTL_SECONDS = 3600

_jobs: dict = {}
_lock = threading.Lock()


def submit_job(user_input: str, runner: Callable[[str], dict]) -> str:
    """질문을 큐에 넣고 job_id를 즉시 반환. runner는 백그라운드 스레드에서 실행."""
    job_id = uuid.uuid4().hex
    with _lock:
        _cleanup_expired()
        _jobs[job_id] = {"status": "queued", "created_at": time.time()}
    threading.Thread(
        target=_run_job, args=(job_id, user_input, runner), daemon=True
    ).start()
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    with _lock:
        _cleanup_expired()
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _run_job(job_id: str, user_input: str, runner: Callable[[str], dict]) -> None:
    with _lock:
        if job_id not in _jobs:
            return
        _jobs[job_id]["status"] = "running"
    try:
        result = runner(user_input)
        update = {
            "status": "done",
            "output": result["output"],
            "route": result["route_history"],
        }
    except Exception as e:  # noqa: BLE001 — job 단위 격리를 위해 모든 예외 수집
        update = {"status": "error", "error": f"{type(e).__name__}: {e}"}
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(update)


def _cleanup_expired() -> None:
    # 호출자가 _lock을 이미 잡고 있어야 한다.
    now = time.time()
    for jid in [
        jid
        for jid, j in _jobs.items()
        if j["status"] in ("done", "error") and now - j["created_at"] > _JOB_TTL_SECONDS
    ]:
        del _jobs[jid]
