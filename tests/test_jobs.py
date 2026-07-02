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
