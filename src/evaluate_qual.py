"""
RAGAS Evaluation for RAG (정성평가용)
"""

import os
os.environ["RAGAS_MAX_CONCURRENCY"] = "1"

import argparse
import json
from datetime import datetime
from dotenv import load_dotenv
import warnings
warnings.filterwarnings("ignore")

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.metrics import (
    Faithfulness,
    AnswerRelevancy,
    LLMContextPrecisionWithoutReference,
)
from langchain_google_genai import ChatGoogleGenerativeAI
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper

load_dotenv()



TEST_QUESTIONS = [
    "토지 소유권 보존등기 신청절차와 필요한 서류가 뭐야?",
    # "근저당권 말소등기를 신청하려면 어떤 서류가 필요한가요?",
    # "부동산 매매로 인한 소유권 이전등기 절차를 설명해줘",
    # "전세권 설정등기와 임차권 등기의 차이점은 무엇인가요?",
    # "상속으로 인한 부동산 등기 신청 시 필요한 서류는 무엇인가요?"
]



def load_rag_pipeline(chroma_path: str):

    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-large"
    )

    db = Chroma(
        persist_directory=chroma_path,
        embedding_function=embeddings,
        collection_name="real_estate_rag",
    )

    retriever = db.as_retriever(
        search_type="mmr",
        search_kwargs={"k": 5, "fetch_k": 20},
    )

    template = """
당신은 대한민국 부동산 등기 업무 전문가입니다.
제공된 [참고 문서]의 내용을 바탕으로 사용자의 질문에 사실에 근거하여 답변하세요.

지침:
1. 법률적 근거가 문서에 명시되어 있다면 반드시 포함하세요.
2. 문서 내용으로 답변할 수 없는 경우, "확인 불가"라고 답변하세요.
3. 이해하기 쉽게 설명하세요.

[참고 문서]
{context}

[질문]
{question}

[답변]
"""

    prompt = ChatPromptTemplate.from_template(template)

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
    )

    def format_docs(docs):
        return "\n\n".join(doc.page_content for doc in docs)

    rag_chain = (
        {
            "context": retriever | format_docs,
            "question": RunnablePassthrough(),
        }
        | prompt
        | llm
        | StrOutputParser()
    )

    return retriever, rag_chain, embeddings



def build_ragas_samples(retriever, rag_chain, questions):

    samples = []

    for i, question in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {question}")

        retrieved_docs = retriever.invoke(question)
        contexts = [doc.page_content for doc in retrieved_docs]

        print(f"  └─ retrieved {len(contexts)}개 청크")
        for j, doc in enumerate(retrieved_docs, 1):
            page = doc.metadata.get("page", "?")
            print(f"\n[{j}] page={page} | {doc.page_content}")

        answer = rag_chain.invoke(question)

        samples.append(
            SingleTurnSample(
                user_input=question,
                response=answer,
                retrieved_contexts=contexts,
            )
        )

    return samples



def run_ragas_evaluation(samples, embeddings, llm_type: str):

    dataset = EvaluationDataset(samples=samples)

    if llm_type == "gemini":
        ragas_llm = LangchainLLMWrapper(
            ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0, model_kwargs={"seed": 42})
        )
    else:
        ragas_llm = LangchainLLMWrapper(
            ChatOpenAI(model="gpt-4o-mini", temperature=0, model_kwargs={"seed": 42})
        )

    ragas_embeddings = LangchainEmbeddingsWrapper(embeddings)

    metrics = [
        Faithfulness(),
        AnswerRelevancy(),
        LLMContextPrecisionWithoutReference(),
    ]

    print(f"\n  LLM-as-a-Judge 평가 실행 중... (judge={llm_type})")

    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=ragas_llm,
        embeddings=ragas_embeddings,
    )

    return result




if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--llm",  choices=["openai", "gemini"], default="gemini")
    parser.add_argument("--db",   default="./chroma_db/v2", help="Chroma persist_directory")
    args = parser.parse_args()

    db_version = args.db.rstrip("/").split("/")[-1]   # v1 / v2 / v3
    label = f"{args.llm}_{db_version}"

    # print(f"\n{'='*50}")
    # print(f"  RAGAS Evaluation  |  judge={args.llm}  |  db={db_version}")
    # print(f"{'='*50}")

    retriever, rag_chain, embeddings = load_rag_pipeline(args.db)
    samples = build_ragas_samples(retriever, rag_chain, TEST_QUESTIONS)
    result = run_ragas_evaluation(samples, embeddings, args.llm)
