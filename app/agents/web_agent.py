"""웹검색 보강 에이전트.

내부 RAG 답변은 절대 수정하지 않고, 공식 사이트(화이트리스트) 검색 결과를
"최신 정보 참고" 섹션 문자열로만 만들어 뒤에 덧붙인다.

- TAVILY_API_KEY 미설정 시 전체 no-op (JOB_QUEUE_URL 없으면 워커 비활성과 동일 패턴)
- 검색 실패·결과 0건이면 빈 문자열 반환 → 본답변에 영향 없음
- route_history 의 "web" 기록 여부는 supervisor 가 반환값 유무로 결정한다
"""

import os
from datetime import date
from typing import List

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

# 공식 출처만 허용. 블로그·광고성 글이 근거로 끼어들지 못하게 Tavily 레벨에서 강제한다.
OFFICIAL_DOMAINS = [
    "iros.go.kr",    # 대법원 인터넷등기소
    "law.go.kr",     # 국가법령정보센터
    "gov.kr",        # 정부24
    "nts.go.kr",     # 국세청
    "wetax.go.kr",   # 위택스 (지방세)
    "molit.go.kr",   # 국토교통부·주택도시기금
]

MAX_RESULTS = 5

llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,
    timeout=30,
    max_retries=2,
)

_SUMMARY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """당신은 셀프 등기 어시스턴트의 '최신 정보 요약' 담당입니다.
아래 [검색 결과]는 공식 기관 사이트에서 가져온 것입니다.

규칙:
1. 검색 결과에 명시된 내용만 요약하세요. 결과에 없는 수치·절차를 절대 만들지 마세요.
2. 사용자 질문과 관련된 항목만 최대 3개, 각 1줄 불릿(-)으로 요약하세요.
3. 각 불릿 끝에 반드시 (출처: URL) 을 붙이세요.
4. 관련된 내용이 하나도 없으면 정확히 NONE 만 출력하세요."""),
    ("human", """[사용자 질문]
{question}

[검색 결과]
{results}"""),
])


def is_enabled() -> bool:
    return bool(TAVILY_API_KEY)


def _search(query: str) -> List[dict]:
    # tavily 미설치 환경(키도 없는 로컬 테스트 등)에서 import 오류가 나지 않도록 지연 임포트
    from tavily import TavilyClient

    client = TavilyClient(api_key=TAVILY_API_KEY)
    resp = client.search(
        query=query,
        include_domains=OFFICIAL_DOMAINS,
        max_results=MAX_RESULTS,
    )
    return resp.get("results", [])


def _format_results(results: List[dict]) -> str:
    return "\n\n".join(
        f"[{i+1}] {r.get('title', '')}\nURL: {r.get('url', '')}\n{r.get('content', '')[:400]}"
        for i, r in enumerate(results)
    )


def run_web_augment(question: str, fallback: bool = False) -> str:
    """공식 사이트 검색 → 요약 섹션 문자열 반환. 실패 시 빈 문자열.

    fallback=True 는 내부 문서에서 답을 못 찾은 경우로, 안내 문구가 더 강해진다.
    """
    if not is_enabled():
        return ""
    try:
        results = _search(question)
    except Exception:  # noqa: BLE001 — 웹검색 실패가 본답변을 막지 않도록
        return ""
    if not results:
        return ""

    summary = llm.invoke(_SUMMARY_PROMPT.format_messages(
        question=question, results=_format_results(results),
    )).content.strip()
    if not summary or summary == "NONE":
        return ""

    today = date.today().isoformat()
    if fallback:
        note = "※ 내부 매뉴얼에 없는 내용입니다. 진행 전 반드시 해당 공식 사이트에서 직접 확인하세요."
    else:
        note = "※ 매뉴얼 내용과 다른 경우 공식 사이트의 최신 정보가 우선입니다."
    return (
        f"\n\n---\n🔎 최신 정보 참고 (공식 사이트 검색 · {today} 조회)\n"
        f"{summary}\n{note}"
    )
