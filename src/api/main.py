from fastapi import FastAPI
from pydantic import BaseModel
from src.retrieval.rag_chain import build_rag_chain, ask
from loguru import logger

app = FastAPI(title="Medical Chatbot API")
chain = None

@app.on_event("startup")
async def startup_event():
    global chain
    logger.info("Loading RAG chain...")
    chain = build_rag_chain()
    logger.info("Ready!")

class QuestionRequest(BaseModel):
    question: str

@app.post("/ask")
async def ask_question(request: QuestionRequest):
    answer, sources = ask(chain, request.question)
    return {"answer": answer, "sources": sources}

@app.get("/health")
async def health():
    return {"status": "ok"}