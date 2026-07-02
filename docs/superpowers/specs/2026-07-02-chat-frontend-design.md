# 부동산 등기 어시스턴트 — 대화형 프론트엔드 + 비동기 Job API 설계

날짜: 2026-07-02
상태: 승인됨

## 배경

백엔드(FastAPI, `app/`)는 `POST /ask` 동기 방식으로 동작하며 응답에 약 17초가
걸린다. 배포 아키텍처가 ALB에서 SQS 기반 비동기 구조로 변경될 예정이므로,
프론트엔드는 처음부터 "제출 → job ID → polling" 비동기 패턴으로 설계한다.
로컬에서는 SQS 없이 인메모리 큐로 동일한 API 계약을 구현하고, SQS 전환 시
job 저장/조회 함수 내부만 교체한다.

## 범위

- 백엔드: `app/main.py`에 job API 추가 (`POST /jobs`, `GET /jobs/{job_id}`),
  CORS 미들웨어 추가. 핵심 로직(`supervisor`, `rag_agent` 등)은 무수정.
- 프론트엔드: `frontend/` 폴더에 React + Vite 채팅 UI 신규 구축.
- 배포(S3/CloudFront/SQS 인프라)는 이번 범위 밖.

## 백엔드 API 계약

```
POST /jobs
  요청:  {"user_input": "질문"}
  응답:  {"job_id": "<uuid>", "status": "queued"}   (즉시 반환)

GET /jobs/{job_id}
  응답:  {"status": "queued" | "running" | "done" | "error",
          "output": "...",     # done일 때만
          "route":  [...],     # done일 때만
          "error":  "..."}     # error일 때만
  404:   job_id 없음 (만료 포함)

POST /ask, GET /health : 기존 그대로 유지
```

### Job 실행 모델

- 인메모리 dict(`{job_id: {status, output, route, error, created_at}}`) +
  백그라운드 스레드에서 `run_assistant` 실행.
- `_submit_job()` / `_get_job()` 함수로 저장소 접근을 감싼다.
  SQS 전환 시 이 두 함수 내부만 교체 (제출→SQS 발행, 조회→결과 저장소 읽기).
- 완료/실패 job은 생성 1시간 후 자동 삭제 (조회 시점에 lazy cleanup).
- CORS: 개발 편의상 모든 origin 허용 (`allow_origins=["*"]`).
  운영 배포 시 프론트엔드 도메인으로 좁힌다.

## 프론트엔드 구조

```
frontend/
├── index.html
├── package.json
├── vite.config.js
├── .env.development        # VITE_API_URL=http://localhost:8000
└── src/
    ├── main.jsx
    ├── App.jsx              # 전체 레이아웃 (헤더 + 채팅 + 입력)
    ├── api.js               # submitJob(), getJob() — fetch 전담
    ├── useChat.js           # 대화 상태, localStorage, polling 로직
    ├── index.css            # 테마 (CSS 변수)
    └── components/
        ├── ChatWindow.jsx       # 메시지 목록, 자동 스크롤
        ├── MessageBubble.jsx    # 말풍선 + 라우팅 배지 + 오류/재시도
        ├── Composer.jsx         # 입력창 + 전송 버튼
        └── ExampleQuestions.jsx # 빈 화면 예시 질문 카드
```

### 동작 흐름

1. 사용자가 질문 입력 → `submitJob()` → job_id 수신, 사용자 말풍선 +
   로딩 말풍선(타이핑 애니메이션 + 경과 시간) 표시.
2. 2초 간격 polling (`getJob`) → `done`이면 답변 말풍선으로 교체,
   route 배지(rag/writing) 표시.
3. 90초 초과 시 polling 중단, "응답이 지연되고 있습니다" + 재시도 버튼.
4. 대화 내역은 localStorage에 저장/복원. "대화 지우기" 버튼 제공.
5. 처리 중에는 입력창 비활성화 (동시에 1개 질문만).

### 기능 목록 (확정)

- 라우팅 경로 배지 (route_history 기반)
- 처리 중 진행 표시 (애니메이션 + 경과 시간)
- 대화 localStorage 저장
- 예시 질문 버튼 (빈 화면일 때)

### 디자인 테마

- 배경: 짙은 네이비 그라디언트 (#0a1628 → #12294d)
- 카드/말풍선: 반투명 유리질감(glassmorphism), 부드러운 그림자,
  상단 테두리 하이라이트로 입체감
- 포인트 컬러: 코발트블루 (#3b82f6 ~ #60a5fa), 버튼/로딩에 글로우
- 폰트: Pretendard (CDN)

## 에러 처리

- 네트워크 오류/5xx → 오류 말풍선 + 재시도 버튼
- job `error` 상태 → 백엔드가 전달한 에러 요약 표시
- polling 타임아웃(90초) → 지연 안내 + 재시도

## 검증 기준

1. `POST /jobs`가 1초 내 job_id 반환, polling으로 `done` 도달 (curl, Docker)
2. 브라우저에서 질문 → 답변 왕복 성공 (Vite dev 서버 + Docker 백엔드)
3. 기존 `/ask`, `/health` 회귀 없음
4. localStorage 저장/복원, 예시 질문, 오류 표시 동작 확인

## SQS 전환 시 변경 지점 (참고)

- `_submit_job()`: dict 저장 + 스레드 실행 → SQS `SendMessage`
- `_get_job()`: dict 조회 → 결과 저장소(DynamoDB/S3/Redis 등) 조회
- 워커: SQS 폴링해서 `run_assistant` 실행 후 결과 저장소에 기록
- 프론트엔드는 무변경 (API 계약 동일)
