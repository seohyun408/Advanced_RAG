from typing import List, Any
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END

from prompt.prompt import GRADE_PROMPT, REWRITE_PROMPT, GENERATE_PROMPT
from app.retriever import hybrid_search

llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,
    timeout=30,
    max_retries=2,
)
MAX_RETRIES = 2


class RagState(TypedDict):
    question: str
    rewritten_question: str
    sub_queries: List[str]
    documents: List[Any]
    answer: str
    grade_result: str
    retry_count: int
    use_decomp: bool


class GradeResult(BaseModel):
    relevance: str = Field(description="'yes' 또는 'no'")
    reason: str = Field(description="판단 이유")


class SubQueries(BaseModel):
    queries: List[str] = Field(description="분해된 하위 질문 목록 (2~3개)")


grade_llm = llm.with_structured_output(GradeResult)
decomp_llm = llm.with_structured_output(SubQueries)

DECOMP_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """복잡한 질문을 독립적으로 검색 가능한 2~3개의 구체적인 하위 질문으로 분해하세요.
각 하위 질문은 등기 업무 키워드를 포함해 단독 검색이 가능해야 합니다.
재작성된 하위 질문 목록만 출력하세요."""),
    ("human", "질문: {question}"),
])


def _rag_planner_node(state: RagState) -> dict:
    return {}


def _route_from_rag_planner(state: RagState) -> str:
    return "decompose" if state.get("use_decomp") else "retrieve"


def _decompose_node(state: RagState) -> dict:
    result = decomp_llm.invoke(DECOMP_PROMPT.format_messages(question=state["question"]))
    return {"sub_queries": result.queries}


def _retrieve(state: RagState) -> dict:
    sub_qs = state.get("sub_queries") or []
    if sub_qs:
        all_docs, seen, docs = [], set(), []
        for sq in sub_qs:
            all_docs.extend(hybrid_search(sq, top_k=3))
        for d in all_docs:
            if d.page_content not in seen:
                seen.add(d.page_content)
                docs.append(d)
        docs = docs[:5]
    else:
        q = state.get("rewritten_question") or state["question"]
        docs = hybrid_search(q, top_k=5)
    return {"documents": docs, "grade_result": "", "answer": ""}


def _grade_documents(state: RagState) -> dict:
    q = state.get("rewritten_question") or state["question"]
    docs = state["documents"]
    if not docs:
        return {"grade_result": "no"}
    doc_previews = "\n\n".join(
        f"[문서 {i+1}] 출처:{d.metadata.get('breadcrumb', 'N/A')}\n{d.page_content[:250]}"
        for i, d in enumerate(docs[:5])
    )
    result = grade_llm.invoke(GRADE_PROMPT.format_messages(question=q, doc_previews=doc_previews))
    return {"grade_result": result.relevance}


def _rewrite_query(state: RagState) -> dict:
    cur = state.get("rewritten_question") or state["question"]
    n = (state.get("retry_count") or 0) + 1
    rewritten = llm.invoke(REWRITE_PROMPT.format_messages(question=cur)).content.strip()
    return {"rewritten_question": rewritten, "retry_count": n, "sub_queries": [], "use_decomp": False}


def _generate(state: RagState) -> dict:
    q = state.get("rewritten_question") or state["question"]
    docs = state.get("documents") or []
    if state.get("grade_result") != "yes" or not docs:
        return {"answer": "(관련 문서 부족) 제공된 문서에서 확인할 수 없습니다."}
    context = "\n\n".join(d.page_content for d in docs)
    return {"answer": llm.invoke(GENERATE_PROMPT.format_messages(context=context, question=q)).content}


def _route_after_grade(state: RagState) -> str:
    if state.get("grade_result") == "yes":
        return "generate"
    if (state.get("retry_count") or 0) >= MAX_RETRIES:
        return "generate"
    return "rewrite_query"


def _build_rag_graph():
    wf = StateGraph(RagState)
    wf.add_node("rag_planner", _rag_planner_node)
    wf.add_node("decompose", _decompose_node)
    wf.add_node("retrieve", _retrieve)
    wf.add_node("grade_documents", _grade_documents)
    wf.add_node("rewrite_query", _rewrite_query)
    wf.add_node("generate", _generate)
    wf.set_entry_point("rag_planner")
    wf.add_conditional_edges(
        "rag_planner", _route_from_rag_planner,
        {"decompose": "decompose", "retrieve": "retrieve"},
    )
    wf.add_edge("decompose", "retrieve")
    wf.add_edge("retrieve", "grade_documents")
    wf.add_conditional_edges(
        "grade_documents", _route_after_grade,
        {"generate": "generate", "rewrite_query": "rewrite_query"},
    )
    wf.add_edge("rewrite_query", "retrieve")
    wf.add_edge("generate", END)
    return wf.compile()


_rag_app = _build_rag_graph()


def run_rag_agent(query: str, use_decomp: bool = False) -> dict:
    final = _rag_app.invoke({
        "question": query, "rewritten_question": "", "sub_queries": [],
        "documents": [], "answer": "", "grade_result": "", "retry_count": 0,
        "use_decomp": use_decomp,
    })
    docs = final.get("documents") or []
    return {
        "answer": final["answer"],
        "contexts": [d.page_content for d in docs],
        "grade_result": final.get("grade_result", ""),
        "retry_count": final.get("retry_count", 0),
    }
