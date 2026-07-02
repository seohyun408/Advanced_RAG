import time

from app import jobs


def _wait_for(job_id, status, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = jobs.get_job(job_id)
        if job and job["status"] == status:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job did not reach {status} in {timeout}s: {jobs.get_job(job_id)}")


def test_submit_returns_id_and_completes():
    job_id = jobs.submit_job(
        "질문", runner=lambda q: {"output": f"답변:{q}", "route_history": ["planner→rag"]}
    )
    assert isinstance(job_id, str) and job_id
    job = _wait_for(job_id, "done")
    assert job["output"] == "답변:질문"
    assert job["route"] == ["planner→rag"]


def test_runner_error_sets_error_status():
    def boom(q):
        raise RuntimeError("LLM down")

    job_id = jobs.submit_job("질문", runner=boom)
    job = _wait_for(job_id, "error")
    assert "RuntimeError" in job["error"]


def test_unknown_job_returns_none():
    assert jobs.get_job("does-not-exist") is None


def test_expired_done_job_is_cleaned():
    job_id = jobs.submit_job("q", runner=lambda q: {"output": "a", "route_history": []})
    _wait_for(job_id, "done")
    with jobs._lock:
        jobs._jobs[job_id]["created_at"] -= jobs._JOB_TTL_SECONDS + 10
    assert jobs.get_job(job_id) is None
