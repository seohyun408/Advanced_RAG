# SQS + DynamoDB 비동기 워커 전환 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 인메모리 job 저장소를 SQS(작업 큐) + DynamoDB(결과 저장소)로 교체하고, ECS 컨테이너가 직접 SQS를 폴링하는 백그라운드 워커를 추가한다. Lambda는 사용하지 않는다.

**Architecture:** `POST /jobs`는 DynamoDB에 `queued` 레코드를 쓰고 SQS에 job_id를 발행한 뒤 즉시 반환한다. 같은 컨테이너 안의 워커 스레드가 SQS를 롱폴링하며 job을 꺼내 `run_assistant`를 실행하고 결과를 DynamoDB에 기록한 뒤 메시지를 삭제한다. `GET /jobs/{id}`는 DynamoDB에서 읽는다. API 계약(`submit_job`/`get_job` 시그니처, HTTP 응답 형태)은 인메모리 버전과 동일하게 유지해 `main.py`·프론트엔드 변경을 최소화한다.

**Tech Stack:** boto3, SQS, DynamoDB, FastAPI lifespan 백그라운드 스레드.

## Global Constraints

- SQS 큐: `realestate-job-queue` (URL `https://sqs.ap-northeast-2.amazonaws.com/566540245375/realestate-job-queue`), VisibilityTimeout=60s (기존)
- DynamoDB 테이블: `realestate-jobs`, 파티션키 `job_id`(S), TTL 속성 `expires_at`(epoch seconds), job TTL 1시간
- 리전: `ap-northeast-2`
- 환경변수로 리소스 이름 주입: `JOB_QUEUE_URL`, `JOB_TABLE_NAME`, `AWS_REGION`(ECS 기본 제공)
- 로컬 테스트는 boto3를 monkeypatch(스텁)해서 AWS 없이 검증. AWS 실연동은 배포 후 검증.
- `run_assistant`(supervisor)·retriever·agents 코드는 무수정
- 기존 `/ask`, `/health` 유지

---

### Task 1: boto3 의존성 + jobs.py를 SQS/DynamoDB로 교체

**Files:**
- Modify: `requirements.txt`, `app/jobs.py`
- Modify: `tests/test_jobs.py` (AWS 클라이언트 스텁 기반으로 재작성)

**Interfaces:**
- Produces (유지): `submit_job(user_input: str) -> str`, `get_job(job_id: str) -> dict | None`
  - 주의: 기존 `submit_job(user_input, runner)`에서 `runner` 인자를 제거한다. 실행은 워커가 담당하므로 제출은 큐잉만 한다.
  - 신규: `enqueue_only=False` 플래그 없음 — 항상 DynamoDB write + SQS send.
- Produces (워커용): `claim_and_store(job_id, runner)` — 워커가 job 실행 결과를 DynamoDB에 기록. `mark_running(job_id)`, `store_result(job_id, output, route)`, `store_error(job_id, message)`.

- [ ] **Step 1: requirements.txt에 boto3 추가**

`requirements.txt`의 `# Vector DB` 섹션 위에 추가:

```
# AWS (SQS job queue + DynamoDB result store)
boto3>=1.34.0
```

- [ ] **Step 2: 실패하는 테스트 작성 (`tests/test_jobs.py` 전체 교체)**

```python
import time

import app.jobs as jobs


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[Item["job_id"]] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None):
        # 테스트용 단순화: store_* 헬퍼가 넣는 필드만 반영
        item = self.items[Key["job_id"]]
        for placeholder, value in ExpressionAttributeValues.items():
            field = placeholder.lstrip(":")
            item[field] = value

    def get_item(self, Key):
        item = self.items.get(Key["job_id"])
        return {"Item": item} if item else {}


class FakeQueue:
    def __init__(self):
        self.sent = []

    def send_message(self, QueueUrl, MessageBody):
        self.sent.append(MessageBody)
        return {"MessageId": "fake"}


def _install_fakes(monkeypatch):
    table = FakeTable()
    queue = FakeQueue()
    monkeypatch.setattr(jobs, "_get_table", lambda: table)
    monkeypatch.setattr(jobs, "_get_sqs", lambda: queue)
    monkeypatch.setattr(jobs, "QUEUE_URL", "http://fake-queue")
    return table, queue


def test_submit_writes_queued_and_enqueues(monkeypatch):
    table, queue = _install_fakes(monkeypatch)
    job_id = jobs.submit_job("등기 질문")
    assert isinstance(job_id, str) and job_id
    assert table.items[job_id]["status"] == "queued"
    assert queue.sent == [job_id]


def test_get_job_returns_stored_fields(monkeypatch):
    table, _ = _install_fakes(monkeypatch)
    job_id = jobs.submit_job("q")
    jobs.store_result(job_id, "답변", ["planner→rag", "rag"])
    job = jobs.get_job(job_id)
    assert job["status"] == "done"
    assert job["output"] == "답변"
    assert job["route"] == ["planner→rag", "rag"]


def test_store_error(monkeypatch):
    table, _ = _install_fakes(monkeypatch)
    job_id = jobs.submit_job("q")
    jobs.store_error(job_id, "RuntimeError: boom")
    job = jobs.get_job(job_id)
    assert job["status"] == "error"
    assert "RuntimeError" in job["error"]


def test_claim_and_store_runs_runner(monkeypatch):
    table, _ = _install_fakes(monkeypatch)
    job_id = jobs.submit_job("q")
    jobs.claim_and_store(job_id, runner=lambda: {"output": "A", "route_history": ["rag"]})
    job = jobs.get_job(job_id)
    assert job["status"] == "done"
    assert job["output"] == "A"


def test_claim_and_store_captures_error(monkeypatch):
    table, _ = _install_fakes(monkeypatch)
    job_id = jobs.submit_job("q")

    def boom():
        raise RuntimeError("LLM down")

    jobs.claim_and_store(job_id, runner=boom)
    job = jobs.get_job(job_id)
    assert job["status"] == "error"
    assert "RuntimeError" in job["error"]


def test_unknown_job_returns_none(monkeypatch):
    _install_fakes(monkeypatch)
    assert jobs.get_job("nope") is None
```

- [ ] **Step 3: 테스트 실패 확인**

```bash
cd /c/Users/seohyun/OneDrive/2026/Advanced_RAG
docker run --rm -e OPENAI_API_KEY=dummy -e QDRANT_URL=http://dummy:6333 \
  -v "//c/Users/seohyun/OneDrive/2026/Advanced_RAG:/work" advanced-rag:latest \
  sh -c "pip install -q pytest boto3 && cd /work && python -m pytest tests/test_jobs.py -v"
```

Expected: FAIL — `submit_job()` 시그니처 불일치 / `store_result` 등 미정의

- [ ] **Step 4: `app/jobs.py` 전체 교체**

```python
"""SQS(작업 큐) + DynamoDB(결과 저장소) 기반 job 저장소.

- submit_job: DynamoDB에 queued 레코드 write + SQS에 job_id 발행 (실행 안 함)
- 워커(app/worker.py)가 SQS를 폴링해 claim_and_store로 실행/결과 기록
- get_job: DynamoDB 조회 (프론트 polling 대상)
"""

import os
import time
import uuid
from typing import Callable, Optional

import boto3

REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
QUEUE_URL = os.environ.get("JOB_QUEUE_URL", "")
TABLE_NAME = os.environ.get("JOB_TABLE_NAME", "realestate-jobs")
_JOB_TTL_SECONDS = 3600

_sqs = None
_table = None


def _get_sqs():
    global _sqs
    if _sqs is None:
        _sqs = boto3.client("sqs", region_name=REGION)
    return _sqs


def _get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    return _table


def submit_job(user_input: str) -> str:
    """DynamoDB에 queued 레코드를 쓰고 SQS에 job_id를 발행. 즉시 job_id 반환."""
    job_id = uuid.uuid4().hex
    now = int(time.time())
    _get_table().put_item(
        Item={
            "job_id": job_id,
            "status": "queued",
            "user_input": user_input,
            "created_at": now,
            "expires_at": now + _JOB_TTL_SECONDS,
        }
    )
    _get_sqs().send_message(QueueUrl=QUEUE_URL, MessageBody=job_id)
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    resp = _get_table().get_item(Key={"job_id": job_id})
    item = resp.get("Item")
    if not item:
        return None
    result = {"status": item["status"]}
    for key in ("output", "route", "error"):
        if key in item:
            result[key] = item[key]
    return result


def get_user_input(job_id: str) -> Optional[str]:
    """워커가 큐에서 받은 job_id로 원본 질문을 조회."""
    resp = _get_table().get_item(Key={"job_id": job_id})
    item = resp.get("Item")
    return item.get("user_input") if item else None


def mark_running(job_id: str) -> None:
    _update(job_id, {"status": "running"})


def store_result(job_id: str, output: str, route: list) -> None:
    _update(job_id, {"status": "done", "output": output, "route": route})


def store_error(job_id: str, message: str) -> None:
    _update(job_id, {"status": "error", "error": message})


def claim_and_store(job_id: str, runner: Callable[[], dict]) -> None:
    """워커가 호출: runner() 실행 결과/오류를 DynamoDB에 기록."""
    mark_running(job_id)
    try:
        result = runner()
        store_result(job_id, result["output"], result["route_history"])
    except Exception as e:  # noqa: BLE001 — job 단위 격리
        store_error(job_id, f"{type(e).__name__}: {e}")


def _update(job_id: str, fields: dict) -> None:
    names = {f"#{k}": k for k in fields}
    values = {f":{k}": v for k, v in fields.items()}
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in fields)
    _get_table().update_item(
        Key={"job_id": job_id},
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )
```

주의: 테스트의 FakeTable.update_item은 `:field` placeholder에서 `field`를 추출한다. 위 `_update`는 `:status` 등으로 값을 넣으므로 호환된다. `status`는 DynamoDB 예약어라 `#status`로 이스케이프한다 (ExpressionAttributeNames).

- [ ] **Step 5: 테스트 통과 확인**

```bash
docker run --rm -e OPENAI_API_KEY=dummy -e QDRANT_URL=http://dummy:6333 \
  -v "//c/Users/seohyun/OneDrive/2026/Advanced_RAG:/work" advanced-rag:latest \
  sh -c "pip install -q pytest boto3 && cd /work && python -m pytest tests/test_jobs.py -v"
```

Expected: `6 passed`

- [ ] **Step 6: Commit**

```bash
git add requirements.txt app/jobs.py tests/test_jobs.py
git commit -m "feat: back job store with SQS + DynamoDB"
```

---

### Task 2: SQS 폴링 워커 (`app/worker.py`) + main.py 연결

**Files:**
- Create: `app/worker.py`
- Modify: `app/main.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `jobs.get_user_input`, `jobs.claim_and_store`, `jobs.QUEUE_URL`, `jobs._get_sqs`, `run_assistant`
- Produces: `start_worker()` — 데몬 스레드에서 SQS 롱폴링 루프 시작. `process_message(receipt, job_id)` — 단위 처리(테스트 대상).

- [ ] **Step 1: 실패하는 테스트 작성 (`tests/test_worker.py`)**

```python
import app.jobs as jobs
import app.worker as worker


def test_process_one_runs_and_deletes(monkeypatch):
    stored = {}
    deleted = []

    monkeypatch.setattr(jobs, "get_user_input", lambda jid: "질문")
    monkeypatch.setattr(
        jobs, "claim_and_store",
        lambda jid, runner: stored.update({jid: runner()}),
    )
    monkeypatch.setattr(worker, "run_assistant", lambda q: {"output": f"A:{q}", "route_history": ["rag"]})

    class FakeSqs:
        def delete_message(self, QueueUrl, ReceiptHandle):
            deleted.append(ReceiptHandle)

    monkeypatch.setattr(jobs, "_get_sqs", lambda: FakeSqs())
    monkeypatch.setattr(jobs, "QUEUE_URL", "http://fake")

    worker.process_message("receipt-1", "job-123")

    assert stored["job-123"]["output"] == "A:질문"
    assert deleted == ["receipt-1"]
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
docker run --rm -e OPENAI_API_KEY=dummy -e QDRANT_URL=http://dummy:6333 \
  -v "//c/Users/seohyun/OneDrive/2026/Advanced_RAG:/work" advanced-rag:latest \
  sh -c "pip install -q pytest boto3 && cd /work && python -m pytest tests/test_worker.py -v"
```

Expected: FAIL — `No module named 'app.worker'`

- [ ] **Step 3: `app/worker.py` 작성**

```python
"""SQS 롱폴링 워커. ECS 컨테이너의 백그라운드 스레드로 실행된다.

큐에서 job_id를 받아 run_assistant를 실행하고 결과를 DynamoDB에 저장한 뒤
메시지를 삭제한다. run_assistant가 예외를 던져도 claim_and_store가 error로
기록하므로 메시지는 항상 삭제된다(무한 재처리 방지).
"""

import threading

from app import jobs
from app.supervisor import run_assistant


def process_message(receipt_handle: str, job_id: str) -> None:
    user_input = jobs.get_user_input(job_id)
    if user_input is None:
        # 레코드가 만료/삭제됨 — 메시지만 정리
        jobs._get_sqs().delete_message(QueueUrl=jobs.QUEUE_URL, ReceiptHandle=receipt_handle)
        return
    jobs.claim_and_store(job_id, runner=lambda: run_assistant(user_input))
    jobs._get_sqs().delete_message(QueueUrl=jobs.QUEUE_URL, ReceiptHandle=receipt_handle)


def _poll_loop() -> None:
    sqs = jobs._get_sqs()
    while True:
        try:
            resp = sqs.receive_message(
                QueueUrl=jobs.QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,  # 롱폴링
            )
        except Exception:  # noqa: BLE001 — 일시 오류 시 루프 유지
            continue
        for msg in resp.get("Messages", []):
            try:
                process_message(msg["ReceiptHandle"], msg["Body"])
            except Exception:  # noqa: BLE001 — 개별 메시지 실패가 루프를 죽이지 않도록
                pass


def start_worker() -> None:
    if not jobs.QUEUE_URL:
        return  # 큐 미설정 환경(로컬 테스트 등)에서는 워커 비활성
    threading.Thread(target=_poll_loop, daemon=True).start()
```

- [ ] **Step 4: `app/main.py` lifespan에 워커 시작 추가**

`lifespan` 함수를 다음으로 교체:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ChromaDB + BM25 인덱스를 서버 시작 시 미리 로드
    from app.retriever import get_retriever
    get_retriever()
    # SQS 폴링 워커 시작 (JOB_QUEUE_URL 설정 시에만)
    from app.worker import start_worker
    start_worker()
    yield
```

그리고 `create_job` 엔드포인트에서 runner 인자 제거:

```python
@app.post("/jobs")
def create_job(req: QueryRequest):
    job_id = jobs.submit_job(req.user_input)
    return {"job_id": job_id, "status": "queued"}
```

- [ ] **Step 5: `tests/test_api.py`의 job 제출 테스트 수정**

`test_job_submit_and_poll`를 SQS/DynamoDB 스텁 기반으로 교체:

```python
def test_job_submit_and_poll(monkeypatch):
    store = {}

    def fake_submit(user_input):
        store["job-1"] = {"status": "done", "output": f"echo:{user_input}",
                          "route": ["planner→rag", "rag"]}
        return "job-1"

    monkeypatch.setattr(main.jobs, "submit_job", fake_submit)
    monkeypatch.setattr(main.jobs, "get_job", lambda jid: store.get(jid))

    r = client.post("/jobs", json={"user_input": "등기 질문"})
    assert r.status_code == 200
    assert r.json()["status"] == "queued"
    job_id = r.json()["job_id"]

    j = client.get(f"/jobs/{job_id}").json()
    assert j["status"] == "done"
    assert j["output"] == "echo:등기 질문"
    assert j["route"] == ["planner→rag", "rag"]
```

`test_unknown_job_is_404`도 get_job이 None 반환하도록 스텁:

```python
def test_unknown_job_is_404(monkeypatch):
    monkeypatch.setattr(main.jobs, "get_job", lambda jid: None)
    assert client.get("/jobs/nope").status_code == 404
```

- [ ] **Step 6: 전체 테스트 통과 확인**

```bash
docker run --rm -e OPENAI_API_KEY=dummy -e QDRANT_URL=http://dummy:6333 \
  -v "//c/Users/seohyun/OneDrive/2026/Advanced_RAG:/work" advanced-rag:latest \
  sh -c "pip install -q pytest boto3 && cd /work && python -m pytest tests -v"
```

Expected: 모든 테스트 통과 (jobs 6 + worker 1 + api 4)

- [ ] **Step 7: Commit**

```bash
git add app/worker.py app/main.py tests/test_worker.py tests/test_api.py
git commit -m "feat: add SQS polling worker started in FastAPI lifespan"
```

---

### Task 3: AWS 리소스 생성 + IAM 권한

**Files:** 없음 (AWS CLI 작업). 사용자 승인 필요.

- [ ] **Step 1: DynamoDB 테이블 생성 (TTL 포함)**

```bash
AWS="/c/Program Files/Amazon/AWSCLIV2/aws.exe"
"$AWS" dynamodb create-table \
  --table-name realestate-jobs \
  --attribute-definitions AttributeName=job_id,AttributeType=S \
  --key-schema AttributeName=job_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region ap-northeast-2
# 생성 대기 후 TTL 활성화
"$AWS" dynamodb wait table-exists --table-name realestate-jobs --region ap-northeast-2
"$AWS" dynamodb update-time-to-live \
  --table-name realestate-jobs \
  --time-to-live-specification "Enabled=true, AttributeName=expires_at" \
  --region ap-northeast-2
```

- [ ] **Step 2: ECS 태스크 역할에 SQS+DynamoDB 권한 부여**

태스크 정의에 taskRoleArn이 없으므로(현재 null) 역할을 만들고 붙인다:

```bash
# 신뢰 정책
cat > /tmp/ecs-trust.json <<'EOF'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}
EOF
"$AWS" iam create-role --role-name realestate-task-role \
  --assume-role-policy-document file:///tmp/ecs-trust.json --region ap-northeast-2

# 권한 정책 (SQS 송수신/삭제 + DynamoDB CRUD)
cat > /tmp/job-policy.json <<'EOF'
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["sqs:SendMessage","sqs:ReceiveMessage","sqs:DeleteMessage","sqs:GetQueueAttributes"],"Resource":"arn:aws:sqs:ap-northeast-2:566540245375:realestate-job-queue"},
  {"Effect":"Allow","Action":["dynamodb:PutItem","dynamodb:GetItem","dynamodb:UpdateItem"],"Resource":"arn:aws:dynamodb:ap-northeast-2:566540245375:table/realestate-jobs"}
]}
EOF
"$AWS" iam put-role-policy --role-name realestate-task-role \
  --policy-name realestate-job-access --policy-document file:///tmp/job-policy.json
```

- [ ] **Step 3: 태스크 정의에 taskRoleArn + 환경변수 추가 (revision 5)**

기존 revision 4 JSON을 복사해 다음을 추가:
- `"taskRoleArn": "arn:aws:iam::566540245375:role/realestate-task-role"`
- 컨테이너 `environment`에:
  ```json
  "environment": [
    {"name": "JOB_QUEUE_URL", "value": "https://sqs.ap-northeast-2.amazonaws.com/566540245375/realestate-job-queue"},
    {"name": "JOB_TABLE_NAME", "value": "realestate-jobs"}
  ]
  ```

register-task-definition으로 revision 5 등록.

- [ ] **Step 4: 서비스 재배포 (revision 5)**

CI/CD가 `:latest` 이미지를 이미 push하므로, 새 코드가 반영되도록:
```bash
git push  # CI가 이미지 빌드+push
# CI 완료 후 서비스가 최신 task def + 최신 이미지로 재배포
"$AWS" ecs update-service --cluster realestate-cluster --service realestate-service3 \
  --task-definition realestate-task:5 --force-new-deployment --region ap-northeast-2
```

- [ ] **Step 5: 배포 검증**

새 태스크 public IP로:
```bash
curl -s http://<IP>:8000/health
# job 왕복
curl -s -X POST http://<IP>:8000/jobs -H "Content-Type: application/json" -d '{"user_input":"등기 절차"}'
# job_id로 polling → done 확인
```

DynamoDB에 레코드 생성 확인:
```bash
"$AWS" dynamodb scan --table-name realestate-jobs --region ap-northeast-2 --max-items 5
```

---

### Task 4: 프론트엔드 재빌드 (백엔드 IP 반영)

- [ ] **Step 1: 재배포로 IP가 바뀌었으면 `.env.production` 갱신**

```bash
# 현재 실행 태스크의 public IP 확인 후
echo "VITE_API_URL=http://<NEW_IP>:8000" > frontend/.env.production
cd frontend && npm run build
```

- [ ] **Step 2: 빌드 산출물에 IP 반영 확인**

```bash
grep -o "<NEW_IP>" dist/assets/*.js | head -1
```

주의: ECS 태스크는 재배포마다 public IP가 바뀐다. 이는 다음 단계(프론트 S3 배포 전)에서 ALB나 고정 주소 도입으로 해결할 사안. 지금은 현재 IP로 빌드해 동작 확인만 한다.
