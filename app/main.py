from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel

from app.supervisor import run_assistant


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ChromaDB + BM25 인덱스를 서버 시작 시 미리 로드
    from app.retriever import get_retriever
    get_retriever()
    yield


app = FastAPI(title="부동산 등기 어시스턴트", lifespan=lifespan)


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
