# 1. 6주차 Agentic RAG 회고

✅ 기존 실험

| Model                  | Chunk_size | overlap | Faithfulness | Answer Relevancy | Context Precision |
|------------------------|------------|---------|--------------|------------------|-------------------|
| Baseline (Dense)       | 1000       | 150     | 0.799        | 0.973            | 0.850             |
| BM25                   | 1000       | 150     | 0.666        | 0.680            | 0.750             |
| Hybrid Retrieval       | 1000       | 150     | 0.904        | **0.974**        | 0.825             |
| Hybrid + Re-ranker     | 1000       | 150     | **0.917**    | 0.843            | **0.865**         |

- *Context Precision*: 관련 문서를 잘 가져왔는가? (Retriever)
- *Faithfulness*: Context에 근거해서 답했는가? (Generator)
- *Answer Relevancy*: 질문에 잘 답했는가? (Final Answer)

Answer Relevancy가 떨어지는 현상으로 Re-Ranker가 "질문에 답하는 데 필요한 문서 일부까지 제거했을 가능성"이 존재한다. 혹은 문서 임베딩 자체의 문제가 있는지 확인하기 위해 확인하기 위해 문서 임베딩 방법을 변경실행 진행한다. 

---


# 2. 데이터 전처리 변경 후 실험

- 변경 전: PyMuPDF
- 변경 후: pymupdf4llm (PDF를 Markdown으로 변환)

`get_breadcrumb_for_page` 페이지 번호를 받아서 해당 페이지가 속한 섹션의 (section_num, readcrumb) 반환하여 metadata 추가하여 문서 객체 생성한다. 이후 chunk_size=1000, overlap=150로 분할한 Chunk를 OpenAIEmbeddings의 `text-embedding-3-large` 사용하여 임베딩한다.

결과: 327개의 Chunk
```
'format': 'PDF 1.4', 'title': '찾기쉬운 생활법령 - 부동산등기', 'author': '법제처 법제정보담당관'
...
'page_count': 226, 'page_number': 11, 'source': 'real_estatee_manual', 'section_num': '2.1.2', 'section_title': '소유권보존등기 > 토지소유권보존등기 > 제출서류'
```

✅ 변경된 질문으로 전체 재실험 결과

| 구성 | Faithfulness ↑ | Answer Relevancy ↑ | Context Precision ↑ | Retrieve Latency (s) | Generate Latency (s) | Total Latency (s) |
|--------|------------|------------------|-------------------|-------------------------|-------------------------|----------------------|
| Dense | 0.696 | 0.684 | **0.773** | 1.34 | 5.52 | 6.85 |
| BM25 | 0.281 | 0.723 | 0.536 | **0.01** | 5.04 | **5.05** |
| Hybrid | 0.830 | **0.728** | 0.521 | 0.53 | **4.85** | 5.38 |
| Hybrid + Rerank | **0.931** | 0.696 | 0.646 | 426.76 | 7.36 | 434.12 |


---

# 3. Agentic RAG - Golden set 실험결과

지난주 실험 결과 5개의 질문에서 1개에서만 Query Rewrite되는 결과를 확인했다. 모호한 구어체 질문에서는 쿼리 재작성하는 Agentic RAG 방식이 효과적이나 좀더 정확한 실험 진행을 위해 좀더 복잡한 예제 구성하여 테스트 하였다.

```
grade=yes  →  generate (정상 답변 생성)
grade=no   →  rewrite_query (쿼리 재작성) → 재검색
              단, retry >= MAX_RETRIES(2)면 → generate(refusal) 로 강제 이동
```

- Agentic RAG가 도움이 된 질문 유형:
    - 모호한 구어체 질문 (+ 사용자가 처한 상황에 대해 설명한 경우)
    - 하나의 Query 내에 여러개 질문한 경우 (but 너무 복잡하면 Context 부족으로 답하지못함)

- Baseline RAG로 충분했던 질문 유형:
    - 하나의 Query 내에 한 개의 질문만 있는 경우


Golden set v1: `..\data\eval\golden_set_v1.csv` 구성은 아래와 같다. 

```
q_type:
    - factual      # 사실 조회
    - comparison   # 개념 비교
    - procedural   # 절차 안내
    - multi_hop    # 복잡한 질문
    - out_of_scope # 문서 범위 밖
    - safety       # 불법/위험 행위

difficulty:
    - easy
    - medium
    - hard

reasoning:
    - single_hop
    - multi_hop
```

✅ 변경된 질문으로 전체 재실험 결과

| Metric | Baseline RAG | Agentic RAG |
|---------|-------------:|------------:|
| Faithfulness | 0.511 | 0.662 |
| Answer Relevancy | 0.602 | 0.692 |
| Context Precision | 0.413 | 0.852 |
| Context Recall | 0.295 | 0.433 |


✅ Query type 별 Retry 횟수

| Q-Type        | Avg Retry | Max Retry |
|---------------|----------:|----------:|
| comparison    | 1.33      | 2         |
| factual       | 0.33      | 1         |
| multi_hop     | 0.00      | 0         |
| out_of_scope  | 1.67      | 2         |
| procedural    | 0.00      | 0         |
| safety        | 2.00      | 2         |


