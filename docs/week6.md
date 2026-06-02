## 1. 5주차 Retrieval 회고

### 1-1. RAG Baseline (Hybrid+Rerank RAG)

Dense / BM25 / Hybrid / Hybrid+Rerank 중 **Hybrid + Reranker** 최종 선택

| Model                  | Chunk_size | overlap | Faithfulness | Answer Relevancy | Context Precision |
|------------------------|------------|---------|--------------|------------------|-------------------|
| Baseline (Dense)       | 1000       | 150     | 0.799        | 0.973            | 0.850             |
| BM25                   | 1000       | 150     | 0.666        | 0.680            | 0.750             |
| Hybrid Retrieval       | 1000       | 150     | 0.904        | **0.974**        | 0.825             |
| Hybrid + Re-ranker     | 1000       | 150     | **0.917**    | 0.843            | **0.865**         |

- *Context Precision*: 관련 문서를 잘 가져왔는가? (Retriever)
- *Faithfulness*: Context에 근거해서 답했는가? (Generator)
- *Answer Relevancy*: 질문에 잘 답했는가? (Final Answer)

**선택 이유**: RAGAS 정량지료에 근거하여 채책하였다. Hybrid + Reranker는 모든 전략 중 Faithfulness(0.917)와 Context Precision(0.865)이 가장 높다. Re-ranker 사용시, Answer Relevancy가 소폭 하락한 것은 관련 없는 문서를 제거하는 과정에서 답변에 다양한 문맥 정보가 일부 제거되어 답변 생성에 활용 가능한 정보가 제한되었을 가능성이 있다. (또한 평가 질문이 5개라는 점도 고려해야 한다.)

BM25는 "검색어 단어가 문서에 얼마나 많이 등장하는지(Exact Match)"를 보고, Dense Retrieval은 "문서의 의미가 얼마나 비슷한지"를 보고 찾는다. 따라서 "소유권 보존등기", "소유권 이전등기"와 같이 용어가 비슷한 등기 업무를 정확하게 찾아낼 수 있는 BM25 방법론을 결합한 Hybrid 방식이 효과적이다. 


### 1-2. Agentic 구조의 필요성

Agentic 구조는 **계획 수립, 도구 활용, 반복 검색 및 결과 검증** 과정을 수행한다. 때문에 단순 정보 조회가 아닌 복잡한 쿼리에 대응하기에는 Agentic RAG 구조가 적합하다. 이는 검색 결과를 스스로 평가하고 부족한 정보를 재탐색함으로써 검색 실패로 인한 오류를 줄이고 보다 신뢰성 있는 답변 생성을 가능하게 한다. 주로 

- Agentic RAG로 풀어가면 좋을 문제 
    - (비교 질문) 전세권 설정등기와 임차권 등기의 차이점은 무엇인가요?
    - (복합 조건) 미성년자가 상속으로 부동산을 취득했을 때 등기 신청은 누가 하나요?
    - (관련 정보가 여러 Section에 분산된 경우) `근저당권 말소등기 절차와 준비서류를 알려주세요`
        ➔ query rewrite로 분리하여 검색하기 !


---

## 2. Agentic RAG

LangGraph 기반 Agentic RAG 구현

- 테스트 질문: 5주차와 동일한 5개 질문 세트
- Embedding 모델: `text-embedding-3-large` 
- LLM: `gpt-4o-mini` 
- Judge LLML: `gemini-2.5-flash`
- Vector DB: ChromaDB, `real_estate_RAG`
- 변경 사항: Agentic routing 구조 (grade → rewrite → retry)


```python
class GraphState(TypedDict):
    question: str            # 질문
    rewritten_question: str  # rewrite 질문
    documents: List[Any]     # 검색된 문서 목록
    answer: str              # 생성된 답변
    grade_result: str        # 'sufficient' 또는 'insufficient'
    retry_count: int         # 재시도 횟수 (최대 MAX_RETRIES=3)
    route_history: list      # 라우팅 경로 추적 
    latency: float           # 총 처리 시간
    error_case_id: str
```


### 2-1. retrieve 
- 기존의 Retriever 사용


### 2-2. grade
- 검색된 문서 5개 Merge
- grade_documents: **LLM Judge** vs Threshold 기반
- pydantic을 사용하여 structured output 답변 출력 (Retrieval된 Context가 관련있는지 yes/no)

    ```
    질문: 상속등기 절차를 알려줘

    검색된 문서:

    [문서 1]
    ...

    [문서 2]
    ...

    [문서 3]
    ...

    위 문서들이 질문에 답하기에 충분히 관련 있는지 판단하세요. (Prompt)
    ```


### 2-3. rewrite_query 
- 쿼리 재작성 후, retry 횟수 더하기


### 2-4. generate
- *retry_count* 모두 시도 후에도 *grade_result=no*이면 답변 불가 처리

    ```
    - grade='yes' -> generate
    - grade='no' + retry_count < MAX_RETRIES -> rewrite_query
    - grade='no' + retry_count >= MAX_RETRIES -> generate (generate node내부에서 답변 불가 처리)
    ```


### 2-5 LangGraph 플로우
    ```
    START([질문 입력]) --> retrieve

    retrieve["retrieve\n---\nHybrid Reranker로 top-5 문서 검색\nrewritten_question 우선, 없으면 question 사용"]

    retrieve --> grade_documents

    grade_documents["grade_documents\n---\nLLM Judge (Structured Output)\n상위 3개 문서 미리보기로 관련성 판단\n→ sufficient / insufficient"]

    grade_documents -->|"grade == sufficient"| generate
    grade_documents -->|"grade == insufficient\n&& retry_count < MAX_RETRIES"| rewrite_query
    grade_documents -->|"grade == insufficient\n&& retry_count >= MAX_RETRIES"| generate

    rewrite_query["rewrite_query\n---\nLLM으로 질문 재작성\n법률 키워드 추가, 구체화\nretry_count += 1"]

    rewrite_query --> retrieve

    generate["generate\n---\n(grade == sufficient) → context 기반 답변 생성\n(grade == insufficient) → 답변 불가 처리\n'제공된 문서에서 확인할 수 없습니다.'"]

    generate --> END([END])
    ```


---

## 3. Main Result (Latency 측정 추가)







---

## 3. Reflect 추가 

> retrieve → grade_documents → rewrite_query → generate → reflect



---

## 4. Main Result



---

## 5. Self-RAG & CRAG

