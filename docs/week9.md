# 전체 아키텍처 점검 (Re)

### 현재 구현완료

- Document Parser: `pymupdf4llm`
- Agentic RAG `(Hybrid Search + Re-ranking + Evaluation)`
- 20개의 Golden set (사실, 비교, 절차, 범위 밖, 불법/위험)
    - 사실 : single_hop
        *ex. 간단한 개념 확인, 문서 체크리스트*
    - 비교 : Sub-query 작성, multi_hop, Retry
        *ex. 토지권소유보존등기 토지권소유이전등기 차이?*
    - 절차 : multi_hop, Retry
        *ex. 등기 처리 절차 관련 질문* 
    - 범위 밖 : 모르면 모른다고 대답하기 (추후 웹서칭으로 연결)
        *ex. 부동산 등기 이외의 질문*
    - 불법/위험 : 가드레일에서 막아주기
        *ex. 공격, 개인정보 관련 질문 등*


### 변경사항 (제거)

- Re-Ranker 제거 
    - bge-reranker가 Retrieve latency 유발 (300~400s) (local 이슈)
    - Evaluate ➔ 재검색 루프가 일부 보완해줄 것으로 기대
    - 성능 하락 비교하고 제거할 것 (음...)

| Configuration | Faithfulness | Answer Rel. | Context Precision | Context Recall | Latency (s) |
|---------------|-------------:|-------------:|-------------------:|---------------:|------------:|
| Baseline RAG | 0.476 | **0.692** | 0.547 | 0.194 | **4.80** |
| Agentic RAG (without Rerank) | 0.514 | 0.524 | 0.686 | 0.278 | 8.58 |
| Agentic RAG (with Rerank) | **0.662** | 0.654 | **0.828** | **0.417** | 316.10 |

    - Agentic RAG 적용시
        - Faithfulness 향상 (+39.1%)
        - Answer Relevancy 소폭 감소 (-5.4%)
        - Context Precision 향상 (+51.4%)
        - Context Recall 향상 (+114.4%)
        
    - Reranker 제거 시:
        - Faithfulness 감소: -0.148
        - Answer Relevancy 감소: -0.130
        - Context Precision 감소: -0.142
        - Context Recall 감소: -0.139


### Anaylsis

- **Query Rewriting**

    절차(procedural)를 물어보는 질문에서 retry가 많이 발생할 것으로 예상했으나, factual(1건), comparison(3건), out_of_scope(3건), safety(3건) 발생했다.

    1. 법률용어로 쿼리 재작성하여 용어 불일치 해결 
        > 대출 다 갚고 나서 근저당 해제할 때, 신청하는 사람 두 명 중에 권리자가 돈 빌린 사람이에요 빌려준 사람이에요?
        > 대출 상환 후 근저당 해제 등기 신청 시, 권리자와 채무자 간의 관계는 ...
    2. 법적 효력 차이 질문에서 절차 차이 질문으로 변경됨 (실패 케이스 Q6 - False Poisitive)


    - True Positive Retry: 재검색이 실제로 도웅이 된 경우
    - False Positive Retry: 재검색을 했지만 애초에 Retrieval 문제가 아닌 경우 (한번의 Query로 해결될 문제가 아님)
    - False Negative Retry: 재검색을 해야하지만 충분하다고 판단
    - True Negative Retry: 재검색 필요없음


### Component

Supervisor(planner) / Sub-Agent 구조

- **RAG Agent**

single_hop : 단일 검색 1회
multi_hop : sub-query 분해 → 각각 검색 → 검증 → 부족한 sub-query만 골라 재검색 → 종합

- **Request Agent**

필요서류 이메일 초안 작성

- **Document Agent**


### Deployment

- Dense(Qdrant) + Sparse(Memory) : 문서가 늘어나면 Opensearch로 변경하는게 좋음







