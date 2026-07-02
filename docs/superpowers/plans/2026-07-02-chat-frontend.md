# 대화형 프론트엔드 + 비동기 Job API 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FastAPI 백엔드에 비동기 job API(POST /jobs, GET /jobs/{id})를 추가하고, React+Vite 채팅 프론트엔드(짙은 파란색 glassmorphism 테마)를 구축한다.

**Architecture:** 백엔드는 인메모리 job 저장소 + 백그라운드 스레드로 `run_assistant`를 실행하며, 저장소 접근은 `app/jobs.py`의 `submit_job`/`get_job` 두 함수로 감싸 SQS 전환 시 내부만 교체 가능하게 한다. 프론트엔드는 제출→job_id→2초 polling 패턴으로 통신하며, 대화 상태는 `useChat` 훅 + localStorage로 관리한다.

**Tech Stack:** FastAPI, pytest(Docker 컨테이너 안에서 실행), React 18, Vite 5, 순수 CSS(빌드 도구 외 프론트 의존성 없음).

## Global Constraints

- 스펙: `docs/superpowers/specs/2026-07-02-chat-frontend-design.md`
- 기존 `/ask`, `/health` 엔드포인트와 `app/supervisor.py`, `app/agents/`, `app/retriever.py`는 수정 금지
- 프론트 추가 라이브러리 금지 (react, react-dom, vite, @vitejs/plugin-react만)
- 백엔드 테스트는 로컬 Python이 아닌 Docker 이미지 안에서 실행 (이미지에 앱 의존성이 이미 있음)
- job TTL: 완료/실패 후 1시간. polling: 2초 간격, 90초 타임아웃
- 테마: 배경 #0a1628→#12294d 그라디언트, 포인트 #3b82f6~#60a5fa, Pretendard 폰트

---

### Task 1: Job 저장소 모듈 (`app/jobs.py`)

**Files:**
- Create: `app/jobs.py`
- Test: `tests/test_jobs.py` (tests/ 폴더 신규)

**Interfaces:**
- Produces: `submit_job(user_input: str, runner: Callable[[str], dict]) -> str` (job_id 반환, runner 결과 dict는 `output`·`route_history` 키 필요), `get_job(job_id: str) -> dict | None` (dict 키: `status`("queued"|"running"|"done"|"error"), `created_at`, 완료 시 `output`·`route`, 실패 시 `error`)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/__init__.py` 빈 파일 생성 후 `tests/test_jobs.py`:

```python
import time

from app import jobs


def _wait_for(job_id, status, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = jobs.get_job(job_id)
        if job and job["status"] == status:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job did not reach {status} in {timeout}s: {jobs.get_job(job_id)}")


def test_submit_returns_id_and_completes():
    job_id = jobs.submit_job(
        "질문", runner=lambda q: {"output": f"답변:{q}", "route_history": ["planner→rag"]}
    )
    assert isinstance(job_id, str) and job_id
    job = _wait_for(job_id, "done")
    assert job["output"] == "답변:질문"
    assert job["route"] == ["planner→rag"]


def test_runner_error_sets_error_status():
    def boom(q):
        raise RuntimeError("LLM down")

    job_id = jobs.submit_job("질문", runner=boom)
    job = _wait_for(job_id, "error")
    assert "RuntimeError" in job["error"]


def test_unknown_job_returns_none():
    assert jobs.get_job("does-not-exist") is None


def test_expired_done_job_is_cleaned():
    job_id = jobs.submit_job("q", runner=lambda q: {"output": "a", "route_history": []})
    _wait_for(job_id, "done")
    with jobs._lock:
        jobs._jobs[job_id]["created_at"] -= jobs._JOB_TTL_SECONDS + 10
    assert jobs.get_job(job_id) is None
```

- [ ] **Step 2: 테스트 실패 확인 (Docker 안에서 실행)**

```bash
cd /c/Users/seohyun/OneDrive/2026/Advanced_RAG
docker run --rm -e OPENAI_API_KEY=dummy -e QDRANT_URL=http://dummy:6333 \
  -v "//c/Users/seohyun/OneDrive/2026/Advanced_RAG:/work" advanced-rag:latest \
  sh -c "pip install -q pytest && cd /work && python -m pytest tests/test_jobs.py -v"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.jobs'` 계열

- [ ] **Step 3: 구현 (`app/jobs.py`)**

```python
"""인메모리 job 저장소.

SQS 전환 시 submit_job(제출)과 get_job(조회) 내부만 교체한다:
submit → SQS SendMessage, get → 결과 저장소(DynamoDB 등) 조회.
"""

import threading
import time
import uuid
from typing import Callable, Optional

_JOB_TTL_SECONDS = 3600

_jobs: dict = {}
_lock = threading.Lock()


def submit_job(user_input: str, runner: Callable[[str], dict]) -> str:
    """질문을 큐에 넣고 job_id를 즉시 반환. runner는 백그라운드 스레드에서 실행."""
    job_id = uuid.uuid4().hex
    with _lock:
        _cleanup_expired()
        _jobs[job_id] = {"status": "queued", "created_at": time.time()}
    threading.Thread(
        target=_run_job, args=(job_id, user_input, runner), daemon=True
    ).start()
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    with _lock:
        _cleanup_expired()
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _run_job(job_id: str, user_input: str, runner: Callable[[str], dict]) -> None:
    with _lock:
        if job_id not in _jobs:
            return
        _jobs[job_id]["status"] = "running"
    try:
        result = runner(user_input)
        update = {
            "status": "done",
            "output": result["output"],
            "route": result["route_history"],
        }
    except Exception as e:  # noqa: BLE001 — job 단위 격리를 위해 모든 예외 수집
        update = {"status": "error", "error": f"{type(e).__name__}: {e}"}
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(update)


def _cleanup_expired() -> None:
    # 호출자가 _lock을 이미 잡고 있어야 한다.
    now = time.time()
    for jid in [
        jid
        for jid, j in _jobs.items()
        if j["status"] in ("done", "error") and now - j["created_at"] > _JOB_TTL_SECONDS
    ]:
        del _jobs[jid]
```

- [ ] **Step 4: 테스트 통과 확인**

Step 2와 같은 명령. Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add app/jobs.py tests/__init__.py tests/test_jobs.py
git commit -m "feat: add in-memory job store for async job API"
```

---

### Task 2: Job API 엔드포인트 + CORS (`app/main.py`)

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: Task 1의 `jobs.submit_job`, `jobs.get_job`
- Produces: `POST /jobs` → `{"job_id": str, "status": "queued"}`, `GET /jobs/{job_id}` → `{"status": str, "output"?: str, "route"?: list, "error"?: str}` (404 = 없는 job)

- [ ] **Step 1: 실패하는 테스트 작성 (`tests/test_api.py`)**

```python
import os
import time

# app.main import 시 supervisor→rag_agent→retriever 체인이 env를 요구하므로 dummy 주입.
# 실제 외부 연결은 lifespan에서만 일어나며 TestClient는 (context manager 없이) lifespan을 실행하지 않는다.
os.environ.setdefault("OPENAI_API_KEY", "dummy")
os.environ.setdefault("QDRANT_URL", "http://dummy:6333")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402

client = TestClient(main.app)


def test_health_still_works():
    assert client.get("/health").json() == {"status": "ok"}


def test_job_submit_and_poll(monkeypatch):
    monkeypatch.setattr(
        main, "run_assistant",
        lambda q: {"output": f"echo:{q}", "route_history": ["planner→rag", "rag"]},
    )
    r = client.post("/jobs", json={"user_input": "등기 질문"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued"
    job_id = body["job_id"]

    for _ in range(100):
        j = client.get(f"/jobs/{job_id}").json()
        if j["status"] == "done":
            break
        time.sleep(0.05)
    assert j["status"] == "done"
    assert j["output"] == "echo:등기 질문"
    assert j["route"] == ["planner→rag", "rag"]


def test_unknown_job_is_404():
    assert client.get("/jobs/nope").status_code == 404


def test_cors_headers_present():
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "*"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
docker run --rm -e OPENAI_API_KEY=dummy -e QDRANT_URL=http://dummy:6333 \
  -v "//c/Users/seohyun/OneDrive/2026/Advanced_RAG:/work" advanced-rag:latest \
  sh -c "pip install -q pytest && cd /work && python -m pytest tests/test_api.py -v"
```

Expected: `test_job_submit_and_poll`, `test_unknown_job_is_404`, `test_cors_headers_present` FAIL (404/CORS 헤더 없음)

- [ ] **Step 3: `app/main.py` 수정**

전체 파일을 다음으로 교체:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import jobs
from app.supervisor import run_assistant


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ChromaDB + BM25 인덱스를 서버 시작 시 미리 로드
    from app.retriever import get_retriever
    get_retriever()
    yield


app = FastAPI(title="부동산 등기 어시스턴트", lifespan=lifespan)

# 프론트엔드(다른 origin)에서의 호출 허용. 운영 배포 시 도메인으로 좁힐 것.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    user_input: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask")
def ask(req: QueryRequest):
    result = run_assistant(req.user_input)
    return {
        "output": result["output"],
        "route": result["route_history"],
    }


@app.post("/jobs")
def create_job(req: QueryRequest):
    job_id = jobs.submit_job(req.user_input, runner=run_assistant)
    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}")
def read_job(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    resp = {"status": job["status"]}
    for key in ("output", "route", "error"):
        if key in job:
            resp[key] = job[key]
    return resp
```

주의: `create_job`이 모듈 전역 `run_assistant`를 직접 참조해야 monkeypatch가 동작한다 (`jobs.submit_job(req.user_input, runner=run_assistant)`를 함수 안에서 호출 — 위 코드 그대로면 됨).

- [ ] **Step 4: 전체 테스트 통과 확인**

```bash
docker run --rm -e OPENAI_API_KEY=dummy -e QDRANT_URL=http://dummy:6333 \
  -v "//c/Users/seohyun/OneDrive/2026/Advanced_RAG:/work" advanced-rag:latest \
  sh -c "pip install -q pytest && cd /work && python -m pytest tests -v"
```

Expected: `8 passed`

- [ ] **Step 5: 실제 컨테이너로 스모크 테스트**

```bash
cd /c/Users/seohyun/OneDrive/2026/Advanced_RAG
docker build -t advanced-rag:latest .
docker rm -f rag-api 2>/dev/null; docker run -d -p 8000:8000 --env-file .env --name rag-api advanced-rag:latest
# startup 대기 후:
docker exec rag-api python3 -c "
import urllib.request, json, time
r = urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/jobs',
    data=json.dumps({'user_input': '등기 절차 요약'}).encode(),
    headers={'Content-Type': 'application/json'}), timeout=10)
jid = json.loads(r.read())['job_id']
print('job_id:', jid)
for _ in range(60):
    j = json.loads(urllib.request.urlopen(f'http://127.0.0.1:8000/jobs/{jid}', timeout=10).read())
    if j['status'] in ('done', 'error'):
        print(j['status'], str(j)[:200]); break
    time.sleep(2)
"
```

Expected: `job_id: <hex>` 즉시 출력 → 수십 초 내 `done {...output...}`

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_api.py
git commit -m "feat: add async job API endpoints and CORS middleware"
```

---

### Task 3: 프론트엔드 스캐폴드 (Vite + React)

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.js`, `frontend/index.html`, `frontend/.env.development`, `frontend/src/main.jsx`, `frontend/src/App.jsx`(임시), `frontend/src/index.css`(임시)
- Modify: `.gitignore`(node_modules 등), `.dockerignore`(frontend/ 제외)

**Interfaces:**
- Produces: `npm run dev`로 5173 포트에 개발 서버, `import.meta.env.VITE_API_URL` 환경변수

- [ ] **Step 1: Node.js 확인**

```bash
node --version && npm --version
```

Expected: v18 이상. 없으면 https://nodejs.org 에서 LTS 설치 후 재시도.

- [ ] **Step 2: 파일 생성**

`frontend/package.json`:

```json
{
  "name": "registry-assistant-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.1",
    "vite": "^5.4.0"
  }
}
```

`frontend/vite.config.js`:

```js
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
});
```

`frontend/index.html`:

```html
<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>부동산 등기 어시스턴트</title>
    <link
      rel="stylesheet"
      href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css"
    />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

`frontend/.env.development`:

```
VITE_API_URL=http://localhost:8000
```

`frontend/src/main.jsx`:

```jsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

`frontend/src/App.jsx` (임시 — Task 6에서 교체):

```jsx
export default function App() {
  return <h1>부동산 등기 어시스턴트</h1>;
}
```

`frontend/src/index.css` (임시 — Task 6에서 교체):

```css
body { margin: 0; font-family: Pretendard, sans-serif; }
```

- [ ] **Step 3: .gitignore / .dockerignore 갱신**

`.gitignore` 끝에 추가:

```
# frontend
frontend/node_modules/
frontend/dist/
```

`.dockerignore` 끝에 추가 (백엔드 이미지에 프론트 소스 불포함):

```
frontend/
```

- [ ] **Step 4: 설치 + dev 서버 확인**

```bash
cd /c/Users/seohyun/OneDrive/2026/Advanced_RAG/frontend
npm install
npm run dev &
# 몇 초 후:
curl -s http://localhost:5173 | grep -o "<title>[^<]*</title>"
```

Expected: `<title>부동산 등기 어시스턴트</title>`

- [ ] **Step 5: Commit**

```bash
git add frontend/ .gitignore .dockerignore
git commit -m "feat: scaffold React+Vite frontend"
```

---

### Task 4: API 클라이언트 + 채팅 훅 (`api.js`, `useChat.js`)

**Files:**
- Create: `frontend/src/api.js`, `frontend/src/useChat.js`

**Interfaces:**
- Consumes: Task 2의 `POST /jobs`, `GET /jobs/{job_id}`
- Produces: `submitJob(userInput) -> Promise<{job_id, status}>`, `getJob(jobId) -> Promise<{status, output?, route?, error?}>`, `useChat() -> {messages, busy, ask(text), retry(), clear()}` — `messages`: `[{id, role: "user"|"assistant", text, route?, error?, pending?}]`

- [ ] **Step 1: `frontend/src/api.js` 작성**

```js
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function submitJob(userInput) {
  const res = await fetch(`${API_URL}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_input: userInput }),
  });
  if (!res.ok) throw new Error(`요청 실패 (HTTP ${res.status})`);
  return res.json();
}

export async function getJob(jobId) {
  const res = await fetch(`${API_URL}/jobs/${jobId}`);
  if (!res.ok) throw new Error(`상태 조회 실패 (HTTP ${res.status})`);
  return res.json();
}
```

- [ ] **Step 2: `frontend/src/useChat.js` 작성**

```js
import { useCallback, useEffect, useRef, useState } from "react";
import { getJob, submitJob } from "./api.js";

const STORAGE_KEY = "registry-chat-v1";
const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 90000;

function loadMessages() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) ?? [];
  } catch {
    return [];
  }
}

export function useChat() {
  const [messages, setMessages] = useState(loadMessages);
  const [busy, setBusy] = useState(false);
  const lastQuestionRef = useRef(null);

  useEffect(() => {
    // pending/error 상태는 저장하지 않고 완료된 대화만 보존
    const done = messages.filter((m) => !m.pending);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(done));
  }, [messages]);

  const ask = useCallback(async (text) => {
    const question = text.trim();
    if (!question) return;
    lastQuestionRef.current = question;
    setBusy(true);

    const userMsg = { id: crypto.randomUUID(), role: "user", text: question };
    const pendingId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: pendingId, role: "assistant", text: "", pending: true },
    ]);

    const finish = (patch) => {
      setMessages((prev) =>
        prev.map((m) => (m.id === pendingId ? { ...m, pending: false, ...patch } : m))
      );
      setBusy(false);
    };

    try {
      const { job_id } = await submitJob(question);
      const deadline = Date.now() + POLL_TIMEOUT_MS;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
        const job = await getJob(job_id);
        if (job.status === "done") {
          finish({ text: job.output, route: job.route });
          return;
        }
        if (job.status === "error") {
          finish({ text: "", error: `처리 중 오류가 발생했습니다: ${job.error}` });
          return;
        }
      }
      finish({ text: "", error: "응답이 지연되고 있습니다. 다시 시도해주세요." });
    } catch (e) {
      finish({ text: "", error: e.message || "네트워크 오류가 발생했습니다." });
    }
  }, []);

  const retry = useCallback(() => {
    if (lastQuestionRef.current && !busy) {
      // 실패한 말풍선 쌍을 제거하고 재제출
      setMessages((prev) => prev.slice(0, -2));
      ask(lastQuestionRef.current);
    }
  }, [ask, busy]);

  const clear = useCallback(() => {
    setMessages([]);
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  return { messages, busy, ask, retry, clear };
}
```

- [ ] **Step 3: 문법 확인 (빌드)**

```bash
cd /c/Users/seohyun/OneDrive/2026/Advanced_RAG/frontend && npm run build
```

Expected: `✓ built in ...` (오류 없음)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api.js frontend/src/useChat.js
git commit -m "feat: add API client and chat hook with job polling"
```

---

### Task 5: UI 컴포넌트 + 테마

**Files:**
- Create: `frontend/src/components/ChatWindow.jsx`, `frontend/src/components/MessageBubble.jsx`, `frontend/src/components/Composer.jsx`, `frontend/src/components/ExampleQuestions.jsx`
- Modify: `frontend/src/App.jsx`, `frontend/src/index.css` (임시 내용 교체)

**Interfaces:**
- Consumes: Task 4의 `useChat()`
- Produces: 완성된 채팅 UI

- [ ] **Step 1: `frontend/src/index.css` 교체 (테마)**

```css
:root {
  --bg-top: #0a1628;
  --bg-bottom: #12294d;
  --accent: #3b82f6;
  --accent-light: #60a5fa;
  --text: #e2e8f0;
  --text-dim: #94a3b8;
  --glass: rgba(30, 58, 108, 0.35);
  --glass-border: rgba(96, 165, 250, 0.25);
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: Pretendard, -apple-system, sans-serif;
  color: var(--text);
  background: linear-gradient(180deg, var(--bg-top) 0%, var(--bg-bottom) 100%);
  min-height: 100vh;
}

#root { display: flex; flex-direction: column; min-height: 100vh; }

.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  max-width: 860px;
  margin: 0 auto;
  width: 100%;
  padding: 0 16px;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 4px 14px;
}

.app-header h1 {
  font-size: 1.15rem;
  font-weight: 700;
  margin: 0;
  background: linear-gradient(90deg, var(--accent-light), #93c5fd);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.clear-btn {
  background: none;
  border: 1px solid var(--glass-border);
  color: var(--text-dim);
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.15s;
}
.clear-btn:hover { color: var(--text); border-color: var(--accent); }

.chat-window {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 8px 4px 16px;
}

.bubble {
  max-width: 78%;
  padding: 14px 18px;
  border-radius: 18px;
  line-height: 1.65;
  font-size: 0.95rem;
  white-space: pre-wrap;
  word-break: break-word;
  /* 입체감: 이중 그림자 + 상단 하이라이트 */
  box-shadow:
    0 8px 24px rgba(2, 8, 23, 0.45),
    0 1px 0 rgba(148, 197, 253, 0.15) inset;
}

.bubble.user {
  align-self: flex-end;
  background: linear-gradient(135deg, #2563eb, #3b82f6);
  border-bottom-right-radius: 6px;
  color: #fff;
}

.bubble.assistant {
  align-self: flex-start;
  background: var(--glass);
  border: 1px solid var(--glass-border);
  backdrop-filter: blur(12px);
  border-bottom-left-radius: 6px;
}

.bubble.error { border-color: rgba(248, 113, 113, 0.5); }
.error-text { color: #fca5a5; }

.retry-btn {
  margin-top: 8px;
  background: rgba(59, 130, 246, 0.2);
  border: 1px solid var(--accent);
  color: var(--accent-light);
  border-radius: 8px;
  padding: 5px 14px;
  font-size: 0.82rem;
  cursor: pointer;
}
.retry-btn:hover { background: rgba(59, 130, 246, 0.35); }

.route-badge {
  display: inline-block;
  margin-top: 10px;
  font-size: 0.72rem;
  color: var(--text-dim);
  background: rgba(15, 33, 66, 0.6);
  border: 1px solid var(--glass-border);
  border-radius: 999px;
  padding: 3px 10px;
}

.typing { display: inline-flex; gap: 5px; align-items: center; height: 1.2em; }
.typing span {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--accent-light);
  animation: pulse 1.2s ease-in-out infinite;
  box-shadow: 0 0 8px var(--accent);
}
.typing span:nth-child(2) { animation-delay: 0.2s; }
.typing span:nth-child(3) { animation-delay: 0.4s; }
@keyframes pulse { 0%, 100% { opacity: 0.25; } 50% { opacity: 1; } }

.elapsed { margin-left: 10px; font-size: 0.78rem; color: var(--text-dim); }

.examples {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 12px;
  margin: auto 0;
  padding: 24px 0;
}

.example-card {
  background: var(--glass);
  border: 1px solid var(--glass-border);
  backdrop-filter: blur(12px);
  border-radius: 14px;
  padding: 16px;
  color: var(--text);
  font-size: 0.9rem;
  text-align: left;
  cursor: pointer;
  transition: transform 0.15s, border-color 0.15s;
  box-shadow: 0 8px 24px rgba(2, 8, 23, 0.35);
}
.example-card:hover {
  transform: translateY(-3px);
  border-color: var(--accent);
}

.composer {
  display: flex;
  gap: 10px;
  padding: 14px 0 22px;
}

.composer input {
  flex: 1;
  background: rgba(10, 22, 40, 0.7);
  border: 1px solid var(--glass-border);
  border-radius: 14px;
  padding: 14px 18px;
  color: var(--text);
  font-size: 0.95rem;
  font-family: inherit;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.composer input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
}
.composer input::placeholder { color: var(--text-dim); }

.send-btn {
  background: linear-gradient(135deg, #2563eb, #3b82f6);
  border: none;
  border-radius: 14px;
  color: #fff;
  padding: 0 22px;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(59, 130, 246, 0.4);
  transition: opacity 0.15s, transform 0.1s;
}
.send-btn:hover:not(:disabled) { transform: translateY(-1px); }
.send-btn:disabled { opacity: 0.45; cursor: not-allowed; }
```

- [ ] **Step 2: `frontend/src/components/MessageBubble.jsx`**

```jsx
import { useEffect, useState } from "react";

function Typing({ startedAt }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(t);
  }, [startedAt]);
  return (
    <span className="typing">
      <span /><span /><span />
      <em className="elapsed">{elapsed}초</em>
    </span>
  );
}

export default function MessageBubble({ message, onRetry }) {
  const { role, text, route, error, pending, startedAt } = message;
  const cls = ["bubble", role, error ? "error" : ""].join(" ").trim();
  return (
    <div className={cls}>
      {pending ? (
        <Typing startedAt={startedAt ?? Date.now()} />
      ) : error ? (
        <>
          <div className="error-text">{error}</div>
          {onRetry && (
            <button className="retry-btn" onClick={onRetry}>다시 시도</button>
          )}
        </>
      ) : (
        <>
          {text}
          {route && <div className="route-badge">경로: {route.join(" · ")}</div>}
        </>
      )}
    </div>
  );
}
```

주의: `useChat.js`의 pending 메시지 생성부에 `startedAt: Date.now()`를 추가해야 한다 — Task 4 코드의 `{ id: pendingId, role: "assistant", text: "", pending: true }`를 `{ id: pendingId, role: "assistant", text: "", pending: true, startedAt: Date.now() }`로 수정.

- [ ] **Step 3: `frontend/src/components/ChatWindow.jsx`**

```jsx
import { useEffect, useRef } from "react";
import MessageBubble from "./MessageBubble.jsx";

export default function ChatWindow({ messages, onRetry }) {
  const endRef = useRef(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="chat-window">
      {messages.map((m, i) => (
        <MessageBubble
          key={m.id}
          message={m}
          onRetry={m.error && i === messages.length - 1 ? onRetry : undefined}
        />
      ))}
      <div ref={endRef} />
    </div>
  );
}
```

- [ ] **Step 4: `frontend/src/components/Composer.jsx`**

```jsx
import { useState } from "react";

export default function Composer({ onSend, disabled }) {
  const [text, setText] = useState("");

  const submit = (e) => {
    e.preventDefault();
    if (disabled || !text.trim()) return;
    onSend(text);
    setText("");
  };

  return (
    <form className="composer" onSubmit={submit}>
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={disabled ? "답변을 기다리는 중..." : "등기 관련 질문을 입력하세요"}
        disabled={disabled}
      />
      <button className="send-btn" type="submit" disabled={disabled || !text.trim()}>
        전송
      </button>
    </form>
  );
}
```

- [ ] **Step 5: `frontend/src/components/ExampleQuestions.jsx`**

```jsx
const EXAMPLES = [
  "소유권이전등기에 필요한 서류는 무엇인가요?",
  "전자신청 사용자등록은 어떻게 하나요?",
  "근저당권 말소 절차를 알려주세요",
  "은행에 보낼 서류 요청 이메일을 작성해주세요",
];

export default function ExampleQuestions({ onPick, disabled }) {
  return (
    <div className="examples">
      {EXAMPLES.map((q) => (
        <button key={q} className="example-card" onClick={() => onPick(q)} disabled={disabled}>
          {q}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 6: `frontend/src/App.jsx` 교체**

```jsx
import ChatWindow from "./components/ChatWindow.jsx";
import Composer from "./components/Composer.jsx";
import ExampleQuestions from "./components/ExampleQuestions.jsx";
import { useChat } from "./useChat.js";

export default function App() {
  const { messages, busy, ask, retry, clear } = useChat();

  return (
    <div className="app">
      <header className="app-header">
        <h1>부동산 등기 어시스턴트</h1>
        {messages.length > 0 && (
          <button className="clear-btn" onClick={clear} disabled={busy}>
            대화 지우기
          </button>
        )}
      </header>
      {messages.length === 0 ? (
        <ExampleQuestions onPick={ask} disabled={busy} />
      ) : (
        <ChatWindow messages={messages} onRetry={retry} />
      )}
      <Composer onSend={ask} disabled={busy} />
    </div>
  );
}
```

- [ ] **Step 7: 빌드 확인**

```bash
cd /c/Users/seohyun/OneDrive/2026/Advanced_RAG/frontend && npm run build
```

Expected: `✓ built` (오류 없음)

- [ ] **Step 8: Commit**

```bash
git add frontend/src/
git commit -m "feat: add chat UI components with deep-blue glass theme"
```

---

### Task 6: E2E 검증

**Files:** 없음 (검증만)

- [ ] **Step 1: 백엔드 컨테이너 기동**

```bash
cd /c/Users/seohyun/OneDrive/2026/Advanced_RAG
docker rm -f rag-api 2>/dev/null
docker run -d -p 8000:8000 --env-file .env --name rag-api advanced-rag:latest
```

- [ ] **Step 2: 프론트 dev 서버 기동 + 브라우저 검증**

```bash
cd frontend && npm run dev
```

브라우저(또는 headless 브라우저)에서 `http://localhost:5173` 열고:
1. 예시 질문 카드 4개 표시 확인
2. 예시 질문 클릭 → 로딩 애니메이션 + 경과 시간 표시 → 수십 초 내 답변 + 경로 배지
3. 새로고침 → 대화 유지(localStorage) 확인
4. "대화 지우기" → 예시 화면 복귀
5. 백엔드 중지(`docker stop rag-api`) 후 질문 → 오류 말풍선 + "다시 시도" 버튼

- [ ] **Step 3: 기존 엔드포인트 회귀 확인**

```bash
curl -s http://localhost:8000/health
```

Expected: `{"status":"ok"}` (Step 5에서 중지했다면 다시 시작 후)

- [ ] **Step 4: 최종 commit + push**

```bash
git status   # 누락 파일 확인
git push origin main
```
