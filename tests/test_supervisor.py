import os

os.environ.setdefault("OPENAI_API_KEY", "dummy")
os.environ.setdefault("QDRANT_URL", "http://dummy:6333")

import app.supervisor as supervisor  # noqa: E402


class FakePlan:
    def __init__(self, next, use_decomp=False, reason=""):
        self.next = next
        self.use_decomp = use_decomp
        self.reason = reason


def _fake_planner_llm(plan: FakePlan):
    return type("FakeLLM", (), {"invoke": staticmethod(lambda msgs: plan)})()


def test_reject_short_circuits_before_rag_or_writing(monkeypatch):
    monkeypatch.setattr(
        supervisor, "planner_llm",
        _fake_planner_llm(FakePlan(next="reject", reason="등기 업무와 무관")),
    )
    called = {"rag": False, "writing": False}
    monkeypatch.setattr(supervisor, "run_rag_agent", lambda *a, **k: called.__setitem__("rag", True) or {"answer": "x"})
    monkeypatch.setattr(supervisor, "run_writing_agent", lambda *a, **k: called.__setitem__("writing", True) or "x")

    result = supervisor.run_assistant("오늘 날씨 어때?")

    assert called == {"rag": False, "writing": False}
    assert result["route_history"] == ["planner→reject"]
    assert "등기" in result["output"] or "부동산" in result["output"]


def test_rag_route_still_works(monkeypatch):
    monkeypatch.setattr(
        supervisor, "planner_llm",
        _fake_planner_llm(FakePlan(next="rag", use_decomp=False)),
    )
    monkeypatch.setattr(supervisor, "run_rag_agent", lambda q, use_decomp: {"answer": f"답:{q}"})

    result = supervisor.run_assistant("소유권이전등기 서류는?")

    assert result["output"] == "답:소유권이전등기 서류는?"
    assert result["route_history"] == ["planner→rag", "rag"]


def test_writing_route_still_works(monkeypatch):
    monkeypatch.setattr(
        supervisor, "planner_llm",
        _fake_planner_llm(FakePlan(next="writing")),
    )
    monkeypatch.setattr(supervisor, "run_writing_agent", lambda q: f"이메일:{q}")

    result = supervisor.run_assistant("은행에 서류요청 이메일 써줘")

    assert result["output"] == "이메일:은행에 서류요청 이메일 써줘"
    assert result["route_history"] == ["planner→writing", "writing"]


def test_unrecognized_label_falls_back_to_rag(monkeypatch):
    monkeypatch.setattr(
        supervisor, "planner_llm",
        _fake_planner_llm(FakePlan(next="something_else")),
    )
    monkeypatch.setattr(supervisor, "run_rag_agent", lambda q, use_decomp: {"answer": "fallback"})

    result = supervisor.run_assistant("애매한 질문")

    assert result["route_history"] == ["planner→rag", "rag"]
