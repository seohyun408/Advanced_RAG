
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pymupdf4llm

from dotenv import load_dotenv
load_dotenv(".env")

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from utils.doc_preprocessing import extract_sections, get_breadcrumb_for_page

print("start")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_PATH = os.path.join(BASE_DIR, 'data', 'registration_of_real_estatee_manual.pdf')
DENSE_DB_PATH = os.path.join(BASE_DIR, 'chroma_db', 'real_estatee_manual')
COLLECTION_NAME = 'real_estatee_manual'


sections, all_headings = extract_sections(PDF_PATH)

pages = pymupdf4llm.to_markdown(PDF_PATH, page_chunks=True)

docs = [
    Document(
        page_content=page["text"],
        metadata={
            **page["metadata"],
            "source": "real_estatee_manual",
            "section_num": section_num,
            "section_title": breadcrumb,
        },
    )
    for page in pages
    if page["metadata"]["page_number"] > 5
    for section_num, breadcrumb in [get_breadcrumb_for_page(
        page["metadata"]["page_number"], sections, all_headings
    )]
]
print(f'총 {len(docs)}개 페이지 로드 완료')

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=150,
)
chunks = text_splitter.split_documents(docs)
print(f'청킹 완료: {len(chunks)}개 청크')


for i, chunk in enumerate(chunks[5:7], start=1):
    print(f'\n===== Chunk {i} =====')
    print(chunk.page_content)
    print(f'Metadata: {chunk.metadata}')


embeddings = OpenAIEmbeddings(model='text-embedding-3-large')

db = Chroma.from_documents(
    documents=chunks,
    embedding=embeddings,
    persist_directory=DENSE_DB_PATH,
    collection_name=COLLECTION_NAME,
)
print(f'신규 ChromaDB 생성 완료: {db._collection.count()}개 문서')
