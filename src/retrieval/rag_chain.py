#RAG_CHAIN.py
import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from src.config import LLM_MODEL, TEMPERATURE, TOP_K_RESULTS, VECTORSTORE_DIR, EMBEDDING_MODEL, CHROMA_COLLECTION
from loguru import logger

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

MEDICAL_PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template="""You are HEALIX — an expert medical assistant. Answer clearly and in simple English.

STRICT RULES:
1. Give a CLEAR and COMPLETE answer to the question
2. Use simple language anyone can understand
3. Structure your answer like this:

🔍 WHAT IT IS:
(Explain the condition/topic clearly in 2-3 lines)

⚠️ CAUSES:
(List main causes with 3-4 bullet points)

🩺 SYMPTOMS:
(List common symptoms with 3-4 bullet points)

💊 TREATMENT:
(List treatment options clearly)

👨‍⚕️ WHICH DOCTOR TO VISIT:
(Clearly say which specialist to visit. Examples:
- Skin problems → Visit a Dermatologist
- Heart problems → Visit a Cardiologist
- Eye problems → Visit an Ophthalmologist
- Bone/joint problems → Visit an Orthopedic doctor
- Mental health → Visit a Psychiatrist or Psychologist
- Diabetes/thyroid → Visit an Endocrinologist
- Kidney problems → Visit a Nephrologist
- Lung/breathing → Visit a Pulmonologist
- Stomach/liver → Visit a Gastroenterologist
- Child health → Visit a Pediatrician
- Women's health → Visit a Gynecologist
- Ear/nose/throat → Visit an ENT Specialist
- General illness → Visit a General Physician)

⚕️ IMPORTANT NOTE:
Always consult a qualified doctor for proper diagnosis and treatment. Do not self-medicate.

Context from medical books:
{context}

Question: {question}

Detailed Answer:"""
)

def build_rag_chain():
    logger.info("Loading vectorstore...")
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True}
    )
    vectorstore = Chroma(
        collection_name=CHROMA_COLLECTION,
        embedding_function=embeddings,
        persist_directory=str(VECTORSTORE_DIR)
    )
    retriever = vectorstore.as_retriever(
        search_type="mmr",
        search_kwargs={"k": TOP_K_RESULTS, "fetch_k": 20}
    )
    llm = ChatGroq(
        api_key=GROQ_API_KEY,
        model_name=LLM_MODEL,
        temperature=TEMPERATURE
    )
    chain = (
        {"context": retriever, "question": RunnablePassthrough()}
        | MEDICAL_PROMPT
        | llm
        | StrOutputParser()
    )
    logger.info("RAG chain ready!")
    return chain, retriever

def ask(chain_tuple, question: str):
    chain, retriever = chain_tuple
    answer = chain.invoke(question)
    docs = retriever.invoke(question)
    sources = list(set([
        doc.metadata.get("source", "Unknown").split("\\")[-1]
        for doc in docs
    ]))
    return answer, sources