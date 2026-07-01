from typing import List
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END

from app.agents.rag_agent import run_rag_agent
from app.agents.writing_agent import run_writing_agent

llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,
    timeout=30,
    max_retries=2,
)

# 향후 확장 예정 에이전트 — 이번 범위에서는 미구현(플래그만 유지).
# True 로 바꾸기 전까지 planner 는 rag/writing 으로만 라우팅한다.
ENABLE_DOC_ANALYSIS = False   # 등기부등본·계약서 PDF 분석 에이전트
ENABLE_TAX_CALC = False       # 취득세·등록면허세 등 비용 계산 에이전트
ENABLE_FULL_PROGRESS = False  # 혼합형 '전체 진행 모드'(상태 추적 워크플로우)


class Plan(BaseModel):
    next: str = Field(description="라우팅할 에이전트. 'rag' 또는 'writing'")
    use_decomp: bool = Field(default=False, description="복잡한 질문 시 RAG sub-query 분해")
    reason: str = Field(description="라우팅 이유")


planner_llm = llm.with_structured_output(Plan)

PLANNER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """당신은 셀프 등기 어시스턴트의 라우터입니다.

에이전트:
- rag     : 등기 절차·개념·서류 내용 질의응답 (내부 문서 검색 기반)
- writing : 건설사·은행 등에 보내는 이메일 작성

라우팅 기준:
- 정보/절차/개념/비교 질문  → rag
- 복잡하거나 다단계 질문    → rag,  use_decomp=true
- 이메일 작성 요청          → writing

이유를 한 줄로 설명하고, 계획을 구조화해 출력하세요."""),
    ("human", "사용자 요청: {user_input}"),
])


class SupervisorState(TypedDict):
    user_input: str
    next_agent: str
    use_decomp: bool
    output: str
    route_history: List[str]


def _planner_node(state: SupervisorState) -> dict:
    p = planner_llm.invoke(PLANNER_PROMPT.format_messages(user_input=state["user_input"]))
    agent = p.next if p.next in {"rag", "writing"} else "rag"
    return {
        "next_agent": agent,
        "use_decomp": p.use_decomp,
        "route_history": [f"planner→{agent}"],
    }


def _rag_node(state: SupervisorState) -> dict:
    res = run_rag_agent(state["user_input"], use_decomp=state.get("use_decomp", False))
    return {"output": res["answer"], "route_history": state["route_history"] + ["rag"]}


def _writing_node(state: SupervisorState) -> dict:
    result = run_writing_agent(state["user_input"])
    return {"output": result, "route_history": state["route_history"] + ["writing"]}


def _route(state: SupervisorState) -> str:
    return state["next_agent"]


def _build_supervisor_graph():
    sup = StateGraph(SupervisorState)
    sup.add_node("planner", _planner_node)
    sup.add_node("rag", _rag_node)
    sup.add_node("writing", _writing_node)
    sup.set_entry_point("planner")
    sup.add_conditional_edges("planner", _route, {"rag": "rag", "writing": "writing"})
    sup.add_edge("rag", END)
    sup.add_edge("writing", END)
    return sup.compile()


_supervisor_app = _build_supervisor_graph()


def run_assistant(user_input: str) -> dict:
    return _supervisor_app.invoke({
        "user_input": user_input, "next_agent": "",
        "use_decomp": False, "output": "", "route_history": [],
    })
