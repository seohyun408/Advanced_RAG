# ADR-004: Week 7 평가 체계 설계

**Date**: 2026-06-07  
**Status**: Accepted

---

## Decision

RAGAS 4지표를 기본 평가 체계로 사용하고, 도메인 특화 지표로 **Refusal Accuracy**와 **Routing Accuracy**를 추가했다.  
Baseline RAG와 Agentic RAG의 답변 품질 비교를 위해 **Pairwise LLM-as-judge**를 도입했다.  
PDF 추출 방식을 기존 fitz(폰트 크기 기반 섹션 감지)에서 **pymupdf4llm**으로 교체해 벡터 DB를 재구축했다.

---

## Context

### 왜 pymupdf4llm으로 DB를 재구축했는가?

| 항목 | fitz (week6) | pymupdf4llm (week7) |
|------|-------------|---------------------|
| 표 처리 | 표 셀이 연속 텍스트로 병합되어 구조 손실 | GFM Markdown 테이블로 변환, 구조 보존 |
| 헤딩 감지 | 폰트 크기(≥11.0pt) 기반 → 수동 튜닝 필요 | `#`, `##` 마크다운 헤딩으로 자동 변환 |
| 페이지 메타데이터 | 수동으로 start_page 추적 | `page_chunks=True`로 페이지 번호 자동 부여 |
| 유지보수 | 폰트 크기 변경 시 코드 수정 필요 | PDF 스펙 변경에 더 유연 |

등기 매뉴얼 PDF에는 신청 서류 목록, 절차 테이블이 다수 포함되어 있어 표 구조 보존이 검색 품질에 직접 영향을 준다.

### 왜 RAGAS만으로 부족했는가?

RAGAS 4지표(Faithfulness, Answer Relevancy, Context Precision, Context Recall)는 검색·생성 품질을 정량화하는 데 유용하지만, 본 시스템에서 중요한 아래 케이스를 평가하지 못한다.

1. **거절 정확성**: out_of_scope/safety 질문에서 올바르게 거절했는지 → Refusal Accuracy
2. **라우팅 적절성**: Agentic RAG의 grade→rewrite→retry 판단이 적절했는지 → Routing Accuracy
3. **Evidence Coverage**: 정답에 필요한 핵심 근거를 답변이 모두 다루는지

---

## Alternatives

| 대안 | 검토 결과 | 미채택 이유 |
|------|----------|------------|
| 사람 전수 평가 | 정확도 높음 | 22개 × 2개 시스템 = 44개 답변 수동 채점 → 시간·비용 과다 |
| Pointwise judge만 사용 | 절대 점수 제공 | 두 시스템 간 상대 비교가 어렵고 LLM 점수의 절대적 해석이 불안정 |
| RAGAS 외 다른 평가 프레임워크 (DeepEval, TruLens) | 다양한 지표 제공 | 학습 비용 및 현재 스택(LangChain/RAGAS)과의 통합 복잡도 증가 |
| 모든 문항에 수동 채점 | 가장 신뢰성 높음 | 주기적 평가 자동화 불가, 8주차 freeze 시 재실행 불가 |
| 회귀 테스트 자동화 (week7 내) | 장기적으로 필요 | 이번 주 범위를 초과, 8주차 이후로 연기 |

---

## Trade-off

| 비용 항목 | 내용 |
|-----------|------|
| Golden set 라벨링 공수 | 22개 문항 × (question, ground_truth, reference_context, q_type) 수동 작성 |
| Judge 모델 API 비용 | RAGAS (gemini-2.5-flash) + Pairwise (gemini-2.5-flash) 호출 비용 |
| Context Recall 신뢰도 | ground_truth 작성 방식(상세도)에 따라 recall 값이 민감하게 변함 |
| Judge 편향 가능성 | 생성 LLM(gpt-4o-mini)과 다른 모델(gemini)을 judge로 사용해 self-preference는 완화했으나, gemini 자체 편향 존재 가능 |
| DB 재구축 비용 | pymupdf4llm 청크 임베딩 재생성 → 임베딩 API 호출 비용 발생 |

---

## Consequence

### 이번 평가 결과가 8주차에 어떻게 이어지는가

1. **Benchmark 표 확정**: 7주차 RAGAS 4지표 + Refusal Accuracy + Routing Accuracy 결과를 `docs/benchmark.md`로 정리해 README에 포함
2. **약점 기반 개선 방향 결정**: 질문 유형별 분석에서 확인된 약점 유형 (예: multi_hop Context Recall 낮음, safety Refusal Accuracy 낮음)을 8주차 시스템 개선 우선순위로 반영
3. **8주차 아키텍처 다이어그램**: pymupdf4llm 기반 전처리 → Hybrid+Reranker → Agentic LangGraph 플로우를 최종 아키텍처로 문서화
4. **평가 체계 재사용**: golden_set_v1.csv를 기반으로 회귀 테스트 자동화 스크립트를 작성해 이후 모델/프롬프트 변경 시 기준점으로 활용

### 도메인 특화 메트릭 재정의

| 메트릭 | 정의 | 적용 q_type | week7 결과 |
|--------|------|------------|-----------|
| Refusal Accuracy | 올바르게 거절한 수 / 거절해야 할 전체 수 | out_of_scope, safety | 실행 후 기재 |
| 오거절 수 | 답해야 하는 질문을 거절한 건수 | factual, comparison, multi_hop | 실행 후 기재 |
| Routing Accuracy | 올바른 route 선택 수 / route 판단 필요 전체 수 | all (Agentic RAG only) | 실행 후 기재 |
