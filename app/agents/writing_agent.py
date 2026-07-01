"""이메일/요청 작성 에이전트.

건설사·은행·매도인 등에게 셀프등기에 필요한 서류를 요청하는 이메일 초안을 생성한다.
필요서류는 RAG로 매번 검색하지 않고 `app/data/required_documents.json`(매뉴얼 기반
하드코딩 매핑)에서 결정론적으로 조회해, 누락·환각 없이 본문에 채운다.
"""

import json
from pathlib import Path
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,
    timeout=30,
    max_retries=2,
)

_DOC_MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "required_documents.json"


def _load_doc_map() -> dict:
    with open(_DOC_MAP_PATH, encoding="utf-8") as f:
        return json.load(f)


_DOC_MAP = _load_doc_map()
# '_meta' 같은 설정 키 제외, 실제 시나리오만
SCENARIOS = {k: v for k, v in _DOC_MAP.items() if not k.startswith("_")}


# ── 결정론적 조회 (LLM 불필요, 단위 테스트 대상) ─────────────────────
def lookup_documents(scenario: str, recipient: str) -> Optional[dict]:
    """(시나리오, 수신처) → 요청 서류 묶음. 없으면 None."""
    sc = SCENARIOS.get(scenario)
    if not sc:
        return None
    rc = sc.get("recipients", {}).get(recipient)
    if not rc:
        return None
    return {
        "scenario_label": sc["label"],
        "신청인": sc.get("신청인", ""),
        "recipient": recipient,
        "관계": rc.get("관계", ""),
        "documents": rc["documents"],
    }


def _options_catalog() -> str:
    """LLM 라우터에 보여줄 '시나리오/수신처' 카탈로그 문자열."""
    lines = []
    for key, sc in SCENARIOS.items():
        recipients = ", ".join(sc.get("recipients", {}).keys())
        lines.append(f"- {key} ({sc['label']}) · 수신처: {recipients}")
    return "\n".join(lines)


# ── 수신처 식별 (LLM) ────────────────────────────────────────────────
class RequestTarget(BaseModel):
    scenario: str = Field(description="아래 카탈로그의 시나리오 키 중 하나. 불명확하면 'unknown'")
    recipient: str = Field(description="해당 시나리오의 수신처 키 중 하나. 불명확하면 'unknown'")
    reason: str = Field(description="선택 이유 한 줄")


_router_llm = llm.with_structured_output(RequestTarget)

_ROUTER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """당신은 셀프 등기 어시스턴트의 '서류 요청 이메일' 라우터입니다.
사용자 요청을 보고, 아래 카탈로그에서 어떤 시나리오의 어떤 수신처에 보내는 이메일인지 고르세요.

[카탈로그]
{catalog}

규칙:
- scenario/recipient 는 반드시 카탈로그의 키와 정확히 일치해야 합니다.
- 어느 쪽이든 확신이 없으면 'unknown' 으로 두세요. (지어내지 마세요)"""),
    ("human", "사용자 요청: {user_input}"),
])


# ── 이메일 본문 생성 (LLM, 서류 목록은 JSON에서 주입) ────────────────
_EMAIL_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """당신은 셀프 등기를 진행하는 신청인을 대신해 정중한 비즈니스 이메일 초안을 작성합니다.

작성 규칙:
1. 아래 [요청 서류]에 있는 항목만 빠짐없이 목록으로 요청하세요. 임의로 추가·삭제하지 마세요.
2. 각 서류 옆에 괄호로 용도를 간단히 덧붙여 상대가 이해하기 쉽게 하세요.
3. 발신자가 채워야 할 부분은 대괄호 자리표시자로 남기세요: [본인 성명], [부동산 표시], [연락처], [회신 기한].
4. 한국어, 공손한 존댓말. 제목 1줄 + 본문. 과장·불필요한 미사여구 없이 간결하게.
5. 마지막에 한 줄로 '※ 위 서류는 매뉴얼 기반 초안이며 상대 기관의 요청 양식에 따라 달라질 수 있습니다.'를 덧붙이세요."""),
    ("human", """[상황]
- 등기 유형: {scenario_label}
- 신청인 구조: {applicants}
- 수신처: {recipient} ({relation})

[요청 서류]
{doc_lines}

위 내용으로 서류 요청 이메일 초안을 작성하세요."""),
])


def _format_doc_lines(documents: List[dict]) -> str:
    return "\n".join(f"- {d['서류']} (용도: {d['용도']})" for d in documents)


def _identify_target(user_input: str) -> Tuple[str, str]:
    res = _router_llm.invoke(
        _ROUTER_PROMPT.format_messages(catalog=_options_catalog(), user_input=user_input)
    )
    return res.scenario, res.recipient


def _clarify_message() -> str:
    return (
        "어떤 등기의 어느 상대방에게 보낼 서류 요청 이메일인지 알려주세요.\n\n"
        "현재 지원하는 조합:\n" + _options_catalog()
    )


def run_writing_agent(user_input: str) -> str:
    scenario, recipient = _identify_target(user_input)
    found = lookup_documents(scenario, recipient)
    if found is None:
        return _clarify_message()

    email = llm.invoke(_EMAIL_PROMPT.format_messages(
        scenario_label=found["scenario_label"],
        applicants=found["신청인"],
        recipient=found["recipient"],
        relation=found["관계"],
        doc_lines=_format_doc_lines(found["documents"]),
    ))
    return email.content
