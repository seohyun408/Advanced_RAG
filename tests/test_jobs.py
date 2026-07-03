import app.jobs as jobs


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[Item["job_id"]] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None):
        # 테스트용 단순화: store_* 헬퍼가 넣는 필드만 반영
        item = self.items[Key["job_id"]]
        for placeholder, value in ExpressionAttributeValues.items():
            field = placeholder.lstrip(":")
            item[field] = value

    def get_item(self, Key):
        item = self.items.get(Key["job_id"])
        return {"Item": item} if item else {}


class FakeQueue:
    def __init__(self):
        self.sent = []

    def send_message(self, QueueUrl, MessageBody):
        self.sent.append(MessageBody)
        return {"MessageId": "fake"}


def _install_fakes(monkeypatch):
    table = FakeTable()
    queue = FakeQueue()
    monkeypatch.setattr(jobs, "_get_table", lambda: table)
    monkeypatch.setattr(jobs, "_get_sqs", lambda: queue)
    monkeypatch.setattr(jobs, "QUEUE_URL", "http://fake-queue")
    # 캐시는 기본적으로 미스 처리 (캐싱 동작은 별도 테스트에서 검증)
    monkeypatch.setattr(jobs.cache, "get_cached", lambda q: None)
    return table, queue


def test_submit_writes_queued_and_enqueues(monkeypatch):
    table, queue = _install_fakes(monkeypatch)
    job_id = jobs.submit_job("등기 질문")
    assert isinstance(job_id, str) and job_id
    assert table.items[job_id]["status"] == "queued"
    assert queue.sent == [job_id]


def test_get_job_returns_stored_fields(monkeypatch):
    table, _ = _install_fakes(monkeypatch)
    job_id = jobs.submit_job("q")
    jobs.store_result(job_id, "답변", ["planner→rag", "rag"])
    job = jobs.get_job(job_id)
    assert job["status"] == "done"
    assert job["output"] == "답변"
    assert job["route"] == ["planner→rag", "rag"]


def test_store_error(monkeypatch):
    table, _ = _install_fakes(monkeypatch)
    job_id = jobs.submit_job("q")
    jobs.store_error(job_id, "RuntimeError: boom")
    job = jobs.get_job(job_id)
    assert job["status"] == "error"
    assert "RuntimeError" in job["error"]


def test_claim_and_store_runs_runner(monkeypatch):
    table, _ = _install_fakes(monkeypatch)
    job_id = jobs.submit_job("q")
    jobs.claim_and_store(job_id, runner=lambda: {"output": "A", "route_history": ["rag"]})
    job = jobs.get_job(job_id)
    assert job["status"] == "done"
    assert job["output"] == "A"


def test_claim_and_store_captures_error(monkeypatch):
    table, _ = _install_fakes(monkeypatch)
    job_id = jobs.submit_job("q")

    def boom():
        raise RuntimeError("LLM down")

    jobs.claim_and_store(job_id, runner=boom)
    job = jobs.get_job(job_id)
    assert job["status"] == "error"
    assert "RuntimeError" in job["error"]


def test_unknown_job_returns_none(monkeypatch):
    _install_fakes(monkeypatch)
    assert jobs.get_job("nope") is None


def test_submit_cache_hit_skips_queue(monkeypatch):
    table, queue = _install_fakes(monkeypatch)
    monkeypatch.setattr(
        jobs.cache, "get_cached",
        lambda q: {"output": "캐시된 답변", "route": ["planner→rag", "rag"]},
    )
    job_id = jobs.submit_job("반복 질문")
    # 캐시 히트 시 SQS로 안 나가고 즉시 done으로 기록됨
    assert queue.sent == []
    job = jobs.get_job(job_id)
    assert job["status"] == "done"
    assert job["output"] == "캐시된 답변"
    assert job["route"] == ["planner→rag", "rag"]


def test_claim_and_store_populates_cache(monkeypatch):
    table, _ = _install_fakes(monkeypatch)
    stored = {}
    monkeypatch.setattr(
        jobs.cache, "store_cached",
        lambda q, output, route: stored.update({"q": q, "output": output, "route": route}),
    )
    job_id = jobs.submit_job("새 질문")
    jobs.claim_and_store(
        job_id, user_input="새 질문",
        runner=lambda: {"output": "새 답변", "route_history": ["rag"]},
    )
    assert stored == {"q": "새 질문", "output": "새 답변", "route": ["rag"]}


def test_claim_and_store_does_not_cache_on_error(monkeypatch):
    table, _ = _install_fakes(monkeypatch)
    called = []
    monkeypatch.setattr(jobs.cache, "store_cached", lambda *a: called.append(a))
    job_id = jobs.submit_job("질문")

    def boom():
        raise RuntimeError("boom")

    jobs.claim_and_store(job_id, user_input="질문", runner=boom)
    assert called == []
