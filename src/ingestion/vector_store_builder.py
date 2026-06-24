from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from src.config import VECTORSTORE_DIR, EMBEDDING_MODEL, CHROMA_COLLECTION
from loguru import logger

def get_embeddings():
    logger.info("Loading embedding model...")
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True}
    )

def build_vectorstore(chunks):
    embeddings = get_embeddings()
    logger.info(f"Building vectorstore with {len(chunks)} chunks...")
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=CHROMA_COLLECTION,
        persist_directory=str(VECTORSTORE_DIR)
    )
    logger.info("Vectorstore built and saved!")
    return vectorstore

def load_vectorstore():
    embeddings = get_embeddings()
    return Chroma(
        collection_name=CHROMA_COLLECTION,
        embedding_function=embeddings,
        persist_directory=str(VECTORSTORE_DIR)
    )