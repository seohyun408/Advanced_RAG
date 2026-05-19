import os
import re
from dotenv import load_dotenv

from langchain_core.documents import Document

# from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from unstructured.partition.pdf import partition_pdf

from utils.doc_preprocessing import extract_sections, get_breadcrumb

load_dotenv()


# ------------------------------------------------------------------
# 1. Load document
# ------------------------------------------------------------------

PDF_PATH = "./data/registration_of_real_estatee_manual.pdf"
sections, all_headings = extract_sections(PDF_PATH)
print(f"추출된 섹션 수: {len(sections)}")
print(f"전체 헤딩 수 (중간 포함): {len(all_headings)}")

# for i, s in enumerate(sections[:5]):
#     print(f"\n--- section[{i}] ---")
#     print(f"  num       : {s['num']}")
#     print(f"  title     : {s['title']}")
#     print(f"  start_page: {s['start_page']}")
#     print(f"  content   : {repr(s['content'][:200])}")

# print("\n--- all_headings (전체) ---")
# for num, title in list(all_headings.items())[:20]:
#     print(f"  {num:<10} : {title}")


section_docs = [
    Document(
        page_content=re.sub(r'\n+', ' ', s["content"]).strip(),
        metadata={
            "section_num": s["num"],
            "section_title": s["title"],
            "breadcrumb": get_breadcrumb(s["num"], all_headings),
            "start_page": s["start_page"],
        },
    )
    for s in sections
    if s["content"].strip()
]

# print(f"\n--- section_docs (총 {len(section_docs)}개) ---")
# for i, doc in enumerate(section_docs[:5]):
#     print(f"\n  [doc {i}]")
#     print(f"  breadcrumb : {doc.metadata['breadcrumb']}")
#     print(f"  section_num: {doc.metadata['section_num']}")
#     print(f"  start_page : {doc.metadata['start_page']}")
#     print(f"  page_content: {repr(doc.page_content[:200])}")

# ------------------------------------------------------------------
# 2. Chunking
# ------------------------------------------------------------------

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=150,
    separators=["\n\n", "\n", ". ", " ", ""],
)
chunks = [c for c in text_splitter.split_documents(section_docs) if c.page_content.strip()]

print(f"총 섹션: {len(section_docs)}  →  총 청크: {len(chunks)}")


# ------------------------------------------------------------------
# 3. Embedding + Vector DB
# ------------------------------------------------------------------

embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

db = Chroma.from_documents(
    documents=chunks,
    embedding=embeddings,
    persist_directory="./chroma_db/v10",
    collection_name="real_estate_rag"
)

retriever = db.as_retriever(search_kwargs={"k": 5})

# ------------------------------------------------------------------
# 4. LLM + Prompt
# ------------------------------------------------------------------

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

prompt = ChatPromptTemplate.from_template(
    """
당신은 대한민국 부동산 등기 전문가입니다.

아래 문서를 기반으로만 답변하세요.
문서에 없는 내용은 추측하지 마세요.

[문서]
{context}

[질문]
{question}

[답변]
"""
)


# ------------------------------------------------------------------
# 5. RAG 실행 함수 (가장 직관적인 방식)
# ------------------------------------------------------------------
def run_rag(query: str):

    # 1) retrieve
    retrieved_docs = retriever.invoke(query)

    # 2) context 만들기
    context = "\n\n".join(
        [doc.page_content for doc in retrieved_docs]
    )

    # 3) prompt 생성
    messages = prompt.format_messages(
        context=context,
        question=query
    )

    # 4) LLM 호출
    response = llm.invoke(messages)

    # 5) 결과 반환
    return response.content


# ------------------------------------------------------------------
# 6. 실행
# ------------------------------------------------------------------
if __name__ == "__main__":

    query = "토지 소유권 보존등기 신청절차와 필요한 서류가 뭐야?"

    print("\n[QUESTION]")
    print(query)

    print("\n[ANSWER]")
    answer = run_rag(query)
    print(answer)