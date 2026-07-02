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
    # SQS 폴링 워커 시작 (JOB_QUEUE_URL 설정 시에만)
    from app.worker import start_worker
    start_worker()
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
    job_id = jobs.submit_job(req.user_input)
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
