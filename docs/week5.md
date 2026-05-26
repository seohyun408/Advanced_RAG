## 1. 4주차 실험 회고 (retrospective)

- RAGAS 정량지표에 근거하여 Baseline 설정
4주차 실험에서 다양한 chunking 전략을 비교한 결과, `Section 분리 + Chunk Size 1000 + Overlap 150` 조합이 가장 안정적인 retrieval 성능을 보여 baseline으로 선정하였다. 

- Retrieval 개선이 필요한 이유

- 1. **공통 키워드 오검색**: `절차`, `서류`, `개념및신청인` 등이 모든 소분류에 반복
- 2. **구조적 유사성 문제**: 등기 유형별로 동일한 소분류 구조

실제로 테스트 질의 시, 전혀 관련 없는 분류의 문서가 검색되었으며, 이는 등기 유형별 문서 구조와 소분류 체계가 유사하게 반복되는 구조적 특성 때문인 것으로 분석하였다. 따라서 5주차에서는 **metadata filtering, BM25 기반 sparse retrieval, hybrid search**을 활용하여 정확한 키워드 매칭 능력을 강화하는 방향으로 retrieval 단계를 개선하고자 한다. 이러한 retrieval 품질 개선은 이후 generation 단계의 hallucination 감소와 최종 응답 정확도 향상에 직접적인 영향을 미치기 때문에 필수적인 과정이라고 판단하였다.


## 2. week5_retrieval_strategy

```
Query
  ↓
Hybrid Retrieval (BM25 + Vector)
  ↓
RRF Fusion
  ↓
Top-50 candidates
  ↓
Cross-Encoder rerank
  ↓
Top-5 context
  ↓
LLM generation
```

### 2-1. Hybrid Search: BM25(sparse) + Dense(OpenAI)

- 법률 도메인의 고유 명사 키워드 매칭을 위해 BM25 사용 **Exact-match**
- Dense는 기존 방식과 마찬가지로 `OpenAI Embedding` 사용
- Merge: RFF - LangChain의 `EnsembleRetriever으로` 구현

### 2-2. Cross-Encoder 기반 Re-ranker

- `BAAI/bge-reranker-v2-m3`


## 3. 실험 결과

1. Baseline
2. BM25
3. Hybrid Search 구현
4. Re-ranking 구현

| Model                  | Chunk_size | overlap | Faithfulness | Answer Relevancy | Context Precision |
|------------------------|------------|---------|--------------|------------------|-------------------|
| Baseline (Dense)       | 1000       | 150     | 0.799        | 0.973            | 0.850             |
| BM25                   | 1000       | 150     | 0.666        | 0.680            | 0.750             |
| Hybrid Retrieval       | 1000       | 150     | 0.904        | 0.974            | 0.825             |
| Hybrid + Re-ranker     | 1000       | 150     | 0.917        | 0.843            | 0.865             |


Hybrid + Re-ranker 방식은 Answer Relevancy가 다소 감소하였지만, 모든 retrieval 전략 중 가장 높은 Faithfulness와 Context Precision 성능을 보인다. 이는 re-ranking 과정이 질문과 관련성이 낮은 문서를 효과적으로 제거하고, 보다 정확하고 신뢰할 수 있는 문맥 정보를 LLM에 제공했음을 의미한다. 특히 RAG 시스템에서는 retrieval 단계의 오류가 곧 hallucination과 잘못된 응답으로 이어질 수 있기 때문에, 생성 답변이 실제 근거 문서에 충실하게 기반하는 것이 매우 중요하다

- 선택 옵션: Hybrid + Re-ranker
    - 정량지료에 근거하여 선택 + Faithfulness가 더 중요한 도메인이고 생각함
    - 포기한 것: latency(Cross-Encoder 추론) 및 구현 복잡도 증가
- 선택하지 않은 옵션: BM25
    - Answer Relevancy 0.680, Faithfulness 0.666으로 전 지표 최하위
    - 동의어·문맥 질문에 취약, 단독 사용 불가 판단
- 선택하지 않은 옵션: Baseline Dense
    - 높지않은 Faithfulness, 할루시네이션 발생 위험
- 선택하지 않은 옵션: Hybrid Retrieval 


## 4. Future Work

- Agentic RAG로 풀어가면 좋을 문제 
    - (비교 질문) 전세권 설정등기와 임차권 등기의 차이점은 무엇인가요?
    - (복합 조건) 미성년자가 상속으로 부동산을 취득했을 때 등기 신청은 누가 하나요?
    - (관련 정보가 여러 Section에 분산된 경우)
- Self-Query Retriever (메타데이터 필터링)
- `main` 파일에 구현 & 정리




