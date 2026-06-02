from langchain_core.prompts import ChatPromptTemplate

GRADE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """당신은 부동산 등기 문서 관련성 평가 전문가입니다.
                검색된 문서들이 질문에 답하기에 충분히 관련이 있는지 판단하세요.

                판단 기준:
                - yes: 문서 중 적어도 2개 이상이 질문의 핵심 내용을 직접적으로 다루고 있음
                - no: 문서들이 질문과 무관하거나, 핵심 정보가 없음"""),

    ("human", """질문: {question}     
                검색된 문서 (상위 5개):
                {doc_previews}
                위 문서들이 질문에 답하기에 충분히 관련 있는지 판단하세요.""")
])



REWRITE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """당신은 법률 문서 검색 전문가입니다.
                다음 질문을 부동산 등기 관련 문서 검색에 더 적합하게 재작성하세요.

                재작성 규칙:
                1. 법률 용어와 등기 업무 관련 키워드를 명시적으로 포함
                2. 질문을 더 구체적으로 만들어 관련 청크가 검색될 수 있도록 함
                3. 동의어나 관련 키워드를 추가 (예: '말소' -> '말소등기 신청 서류 절차')
                4. 재작성된 질문만 출력 (설명 없이)"""),
    ("human", "원래 질문: {question}\n\n재작성된 질문:")
])



GENERATE_PROMPT = ChatPromptTemplate.from_template("""당신은 대한민국 부동산 등기 업무 전문가입니다.
제공된 [참고 문서]의 내용을 바탕으로 사용자의 질문에 사실에 근거하여 답변하세요.

지침:
1. 법률적 근거가 문서에 명시되어 있다면 반드시 포함하세요.
2. 문서 내용으로 답변할 수 없는 경우, '확인 불가'라고 답변하세요.
3. 이해하기 쉽게 설명하세요.

[참고 문서]
{context}

[질문]
{question}

[답변]""")