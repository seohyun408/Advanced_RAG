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

**선택 이유**: RAGAS 정량지료에 근거하여 채택하였다. Hybrid + Reranker는 모든 전략 중 Faithfulness(0.917)와 Context Precision(0.865)이 가장 높다. Re-ranker 사용시, Answer Relevancy가 소폭 하락한 것은 관련 없는 문서를 제거하는 과정에서 답변에 다양한 문맥 정보가 일부 제거되어 답변 생성에 활용 가능한 정보가 제한되었을 가능성이 있다. (또한 평가 질문이 5개라는 점도 고려해야 한다.)

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

    grade_documents -->|"grade == yes"| generate
    grade_documents -->|"grade == no\n&& retry_count < MAX_RETRIES"| rewrite_query
    grade_documents -->|"grade == no\n&& retry_count >= MAX_RETRIES"| generate

    rewrite_query["rewrite_query\n---\nLLM으로 질문 재작성\n법률 키워드 추가, 구체화\nretry_count += 1"]

    rewrite_query --> retrieve

    generate["generate\n---\n(grade == yes) → context 기반 답변 생성\n(grade == no) → 답변 불가 처리\n'제공된 문서에서 확인할 수 없습니다.'"]

    generate --> END([END])
    ```

   
---

## 3. Main Result (Latency 측정 추가)

- 테스트 질문 5개 기준 RAGAS 평가 결과

| 구성 | Faithfulness | Answer Relevancy | Context Precision | 평균 Latency(s) |
|------|:---:|:---:|:---:|:---:|
| Baseline (Hybrid+Reranker) | 0.597 | **0.822** | **0.580** | 182.30 |
| Agentic RAG (LangGraph) | **0.703** | 0.809 | 0.407 | 179.08 |

**Retry 통계** (Agentic RAG 기준)

| 재시도 횟수 | 건수 |
|:---:|:---:|
| 0회 | 4건 |
| 1회 | 1건 |
| 2회 | 0건 |

- Q1 ("부모님이 살아계실 때 집을 미리 자식한테 넘겨주고 싶대요...")만 재시도 1회 발생
  - 원래 구어체 질문 → "부모가 생전에 자녀에게 부동산을 증여하고자 할 때, 상속과의 차이점은 무엇이며, 해당 부동산의 증여등기 절차는 어떻게 진행되나요?" 로 재작성 후 grade=yes 통과

**분석**

- **Faithfulness (0.597 → 0.703)**: Agentic RAG 개선
- **Answer Relevancy (0.822 → 0.809)**: Query 재작성하면서 원래 질문의 의도가 바뀔 가능성
- **Context Precision (0.580 → 0.407)**: 
- **Latency**: 두 방식이 유사. 대부분의 질문이 재시도 없이 처리되어 차이가 크지 않았음


- 실험 질문
  Q1: 부모님이 살아계실 때 집을 미리 자식한테 넘겨주고 싶대요. 상속이랑 다른 건가요? 등기는 어떻게 해요?
  Q2: 새로 지은 건물 처음 등기할 때 뭐가 필요해요?
  Q3: 미성년자가 상속으로 부동산을 취득했을 때 등기 신청은 누가 하나요?
  Q4: 근저당권 말소등기 절차와 준비서류를 알려주세요
  Q5: 가등기 해놨는데 잔금 다 내고 나서 본등기로 바꾸는 방법이 뭐예요?


- 아래 질문에 대해서 제대로 답하지 못함. (Context 부족이라고 답변)
  Q1: 전세권 설정등기와 임차권 등기명령의 차이점은 무엇이며, 각각 어떤 상황에서 선택하는 것이 유리한가요?
  Q2: 공동 상속인이 여러 명인 경우 부동산 상속등기 신청은 어떻게 진행되며, 상속인 중 미성년자가 포함된 경우 절차가 어떻게 달라지나요?
  Q3: 이전등기 신청 시 인감증명서 제출이 필요한 경우와 면제되는 경우는 각각 어떤 상황인가요?
  Q4: 부동산 매매 계약 후 소유권 이전등기를 완료하기 위해 매도인과 매수인이 각각 준비해야 할 서류와 역할은 무엇인가요?
  Q5: 근저당권이 설정된 부동산을 상속받았을 때 상속등기와 근저당권 처리를 어떤 순서로 진행해야 하나요?




---
---

## 4. Reflect 추가 

> retrieve → grade_documents → rewrite_query → generate → reflect

- **Reflect Node**: generate 이후 생성된 답변이 질문에 충분히 답하고 있는지 LLM이 자체 검토
- grade_documents가 "문서가 관련 있는가"를 판단한다면, reflect는 "생성된 답변이 충분한가"를 판단

```
grade='yes' → generate → reflect
                           ↓ (답변 불충분)
                        rewrite_query → retrieve → grade → generate → reflect
                           ↓ (답변 충분 또는 MAX_RETRIES 도달)
                          END
```


---

## 5. Self-RAG & CRAG


