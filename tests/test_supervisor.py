import os

os.environ.setdefault("OPENAI_API_KEY", "dummy")
os.environ.setdefault("QDRANT_URL", "http://dummy:6333")

import app.supervisor as supervisor  # noqa: E402


class FakePlan:
    def __init__(self, next, use_decomp=False, use_web=False, reason=""):
        self.next = next
        self.use_decomp = use_decomp
        self.use_web = use_web
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


# ── 웹검색 보강 (web_augment) ────────────────────────────────────────


def test_web_disabled_skips_augment_even_if_planned(monkeypatch):
    monkeypatch.setattr(
        supervisor, "planner_llm",
        _fake_planner_llm(FakePlan(next="rag", use_web=True)),
    )
    monkeypatch.setattr(supervisor, "run_rag_agent", lambda q, use_decomp: {"answer": "내부 답변"})
    monkeypatch.setattr(supervisor.web_agent, "is_enabled", lambda: False)
    called = []
    monkeypatch.setattr(supervisor.web_agent, "run_web_augment", lambda *a, **k: called.append(1) or "")

    result = supervisor.run_assistant("올해 취득세율?")

    assert called == []
    assert result["output"] == "내부 답변"
    assert result["route_history"] == ["planner→rag", "rag"]


def test_use_web_appends_section_and_route(monkeypatch):
    monkeypatch.setattr(
        supervisor, "planner_llm",
        _fake_planner_llm(FakePlan(next="rag", use_web=True)),
    )
    monkeypatch.setattr(supervisor, "run_rag_agent", lambda q, use_decomp: {"answer": "내부 답변"})
    monkeypatch.setattr(supervisor.web_agent, "is_enabled", lambda: True)
    monkeypatch.setattr(
        supervisor.web_agent, "run_web_augment",
        lambda q, fallback=False: "\n\n---\n🔎 최신 정보",
    )

    result = supervisor.run_assistant("올해 취득세율?")

    assert result["output"] == "내부 답변\n\n---\n🔎 최신 정보"
    assert result["route_history"] == ["planner→rag", "rag", "web"]


def test_insufficient_docs_triggers_web_fallback(monkeypatch):
    # planner 는 use_web=False 였지만 RAG 가 문서 부족이면 fallback 으로 웹검색
    monkeypatch.setattr(
        supervisor, "planner_llm",
        _fake_planner_llm(FakePlan(next="rag", use_web=False)),
    )
    monkeypatch.setattr(
        supervisor, "run_rag_agent",
        lambda q, use_decomp: {"answer": "(관련 문서 부족) 제공된 문서에서 확인할 수 없습니다."},
    )
    monkeypatch.setattr(supervisor.web_agent, "is_enabled", lambda: True)
    seen = {}
    monkeypatch.setattr(
        supervisor.web_agent, "run_web_augment",
        lambda q, fallback=False: seen.update({"fallback": fallback}) or "\n\n---\n🔎 웹 결과",
    )

    result = supervisor.run_assistant("아주 생소한 질문")

    assert seen == {"fallback": True}
    assert result["route_history"] == ["planner→rag", "rag", "web"]


def test_empty_web_section_keeps_route_clean(monkeypatch):
    # 검색 결과가 비면 output/route 모두 그대로 → 캐시 저장도 정상 동작해야 함
    monkeypatch.setattr(
        supervisor, "planner_llm",
        _fake_planner_llm(FakePlan(next="rag", use_web=True)),
    )
    monkeypatch.setattr(supervisor, "run_rag_agent", lambda q, use_decomp: {"answer": "내부 답변"})
    monkeypatch.setattr(supervisor.web_agent, "is_enabled", lambda: True)
    monkeypatch.setattr(supervisor.web_agent, "run_web_augment", lambda q, fallback=False: "")

    result = supervisor.run_assistant("올해 취득세율?")

    assert result["output"] == "내부 답변"
    assert result["route_history"] == ["planner→rag", "rag"]


def test_writing_route_never_uses_web(monkeypatch):
    monkeypatch.setattr(
        supervisor, "planner_llm",
        _fake_planner_llm(FakePlan(next="writing", use_web=True)),
    )
    monkeypatch.setattr(supervisor, "run_writing_agent", lambda q: "이메일")
    monkeypatch.setattr(supervisor.web_agent, "is_enabled", lambda: True)
    called = []
    monkeypatch.setattr(supervisor.web_agent, "run_web_augment", lambda *a, **k: called.append(1) or "x")

    result = supervisor.run_assistant("이메일 써줘")

    assert called == []
    assert result["route_history"] == ["planner→writing", "writing"]
