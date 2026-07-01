import os
import re
from typing import List

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_community.retrievers import BM25Retriever
from qdrant_client import QdrantClient

try:
    from langchain_classic.retrievers import EnsembleRetriever
except ImportError:
    from langchain.retrievers import EnsembleRetriever

QDRANT_URL = os.environ["QDRANT_URL"]
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY")  # 로컬 self-hosted면 없어도 됨
COLLECTION_NAME = os.environ.get("QDRANT_COLLECTION", "real_estatee_manual")


def _korean_tokenizer(text: str):
    cleaned = re.sub("[^가-힣a-zA-Z0-9]", " ", text)
    return [t for t in cleaned.split() if len(t) > 1]


def _build_retriever():
    embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

    qdrant_store = QdrantVectorStore.from_existing_collection(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY,
        collection_name=COLLECTION_NAME,
        embedding=embeddings,
    )

    # BM25용 전체 문서를 Qdrant scroll로 가져와 메모리에 유지
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    all_docs, offset = [], None
    while True:
        batch, offset = client.scroll(
            collection_name=COLLECTION_NAME,
            with_payload=True,
            with_vectors=False,
            limit=256,
            offset=offset,
        )
        all_docs.extend(
            Document(
                page_content=p.payload.get("page_content", ""),
                metadata=p.payload.get("metadata", {}),
            )
            for p in batch
        )
        if offset is None:
            break
    bm25 = BM25Retriever.from_documents(all_docs, k=10, preprocess_func=_korean_tokenizer)

    dense = qdrant_store.as_retriever(
        search_type="mmr",
        search_kwargs={"k": 10, "fetch_k": 20},
    )

    return EnsembleRetriever(retrievers=[bm25, dense], weights=[0.5, 0.5], c=60)


_retriever = None


def get_retriever():
    global _retriever
    if _retriever is None:
        _retriever = _build_retriever()
    return _retriever


def hybrid_search(query: str, top_k: int = 5) -> List[Document]:
    return get_retriever().invoke(query)[:top_k]
