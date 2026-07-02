import app.jobs as jobs
import app.worker as worker


def test_process_one_runs_and_deletes(monkeypatch):
    stored = {}
    deleted = []

    monkeypatch.setattr(jobs, "get_user_input", lambda jid: "질문")
    monkeypatch.setattr(
        jobs, "claim_and_store",
        lambda jid, runner: stored.update({jid: runner()}),
    )
    monkeypatch.setattr(worker, "run_assistant", lambda q: {"output": f"A:{q}", "route_history": ["rag"]})

    class FakeSqs:
        def delete_message(self, QueueUrl, ReceiptHandle):
            deleted.append(ReceiptHandle)

    monkeypatch.setattr(jobs, "_get_sqs", lambda: FakeSqs())
    monkeypatch.setattr(jobs, "QUEUE_URL", "http://fake")

    worker.process_message("receipt-1", "job-123")

    assert stored["job-123"]["output"] == "A:질문"
    assert deleted == ["receipt-1"]
