"""
ChromaDB → Qdrant 마이그레이션 스크립트 (1회 실행)

실행 방법:
    QDRANT_URL=https://xxx.qdrant.io \
    QDRANT_API_KEY=your-key \
    python scripts/upload_to_qdrant.py

환경변수:
    QDRANT_URL      Qdrant Cloud 엔드포인트 (필수)
    QDRANT_API_KEY  Qdrant API 키 (Cloud 사용 시 필수)
    QDRANT_COLLECTION  컬렉션 이름 (기본값: real_estatee_manual)
    CHROMA_DB_PATH  기존 ChromaDB 경로 (기본값: ./chroma_db/real_estatee_manual)
    CHROMA_COLLECTION  ChromaDB 컬렉션 이름 (기본값: real_estatee_manual)
"""

import os
import sys

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

load_dotenv()

QDRANT_URL = os.environ["QDRANT_URL"]
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY")
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "real_estatee_manual")

CHROMA_DB_PATH = os.environ.get(
    "CHROMA_DB_PATH",
    "C:/Users/seohyun/OneDrive/2026/Advanced_RAG/chroma_db/real_estatee_manual",
)
CHROMA_COLLECTION = os.environ.get("CHROMA_COLLECTION", "real_estatee_manual")

EMBEDDING_DIM = 3072  # text-embedding-3-large
BATCH_SIZE = 100


def load_chroma_data() -> dict:
    print(f"ChromaDB 로드 중: {CHROMA_DB_PATH}")
    embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
    db = Chroma(
        persist_directory=CHROMA_DB_PATH,
        embedding_function=embeddings,
        collection_name=CHROMA_COLLECTION,
    )
    raw = db.get(include=["embeddings", "documents", "metadatas"])
    total = len(raw["documents"])
    print(f"  총 {total}개 문서 로드 완료")
    return raw


def create_qdrant_collection(client: QdrantClient):
    existing = [c.name for c in client.get_collections().collections]
    if QDRANT_COLLECTION in existing:
        answer = input(f"컬렉션 '{QDRANT_COLLECTION}'이 이미 존재합니다. 덮어쓰시겠습니까? (y/N): ")
        if answer.strip().lower() != "y":
            print("업로드를 취소합니다.")
            sys.exit(0)
        client.delete_collection(QDRANT_COLLECTION)
        print(f"  기존 컬렉션 삭제 완료")

    client.create_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
    )
    print(f"  컬렉션 '{QDRANT_COLLECTION}' 생성 완료")


def upload_in_batches(client: QdrantClient, raw: dict):
    documents = raw["documents"]
    embeddings = raw["embeddings"]
    metadatas = raw["metadatas"]
    total = len(documents)

    print(f"Qdrant 업로드 시작 (배치 크기: {BATCH_SIZE})")
    for start in range(0, total, BATCH_SIZE):
        end = min(start + BATCH_SIZE, total)
        points = [
            PointStruct(
                id=start + i,
                vector=embeddings[start + i],
                # LangChain QdrantVectorStore가 기대하는 payload 형식
                payload={
                    "page_content": documents[start + i],
                    "metadata": metadatas[start + i] or {},
                },
            )
            for i in range(end - start)
        ]
        client.upsert(collection_name=QDRANT_COLLECTION, points=points)
        print(f"  [{end:>4}/{total}] 업로드 완료")

    print(f"업로드 완료: 총 {total}개 벡터")


def verify(client: QdrantClient):
    info = client.get_collection(QDRANT_COLLECTION)
    count = info.points_count
    print(f"검증: Qdrant 컬렉션 '{QDRANT_COLLECTION}' → {count}개 포인트 확인")


if __name__ == "__main__":
    raw = load_chroma_data()

    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    create_qdrant_collection(client)
    upload_in_batches(client, raw)
    verify(client)
