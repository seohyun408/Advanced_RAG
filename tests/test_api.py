import os
import time

# app.main import 시 supervisor→rag_agent→retriever 체인이 env를 요구하므로 dummy 주입.
# 실제 외부 연결은 lifespan에서만 일어나며 TestClient는 (context manager 없이) lifespan을 실행하지 않는다.
os.environ.setdefault("OPENAI_API_KEY", "dummy")
os.environ.setdefault("QDRANT_URL", "http://dummy:6333")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402

client = TestClient(main.app)


def test_health_still_works():
    assert client.get("/health").json() == {"status": "ok"}


def test_job_submit_and_poll(monkeypatch):
    monkeypatch.setattr(
        main, "run_assistant",
        lambda q: {"output": f"echo:{q}", "route_history": ["planner→rag", "rag"]},
    )
    r = client.post("/jobs", json={"user_input": "등기 질문"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued"
    job_id = body["job_id"]

    for _ in range(100):
        j = client.get(f"/jobs/{job_id}").json()
        if j["status"] == "done":
            break
        time.sleep(0.05)
    assert j["status"] == "done"
    assert j["output"] == "echo:등기 질문"
    assert j["route"] == ["planner→rag", "rag"]


def test_unknown_job_is_404():
    assert client.get("/jobs/nope").status_code == 404


def test_cors_headers_present():
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "*"
