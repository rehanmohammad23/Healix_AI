from src.ingestion.pdf_loader import load_and_chunk_pdfs
from src.ingestion.vector_store_builder import build_vectorstore
from loguru import logger

if __name__ == "__main__":
    logger.info("Starting ingestion pipeline...")
    chunks = load_and_chunk_pdfs()
    build_vectorstore(chunks)
    logger.info("Done! Your medical knowledge base is ready.")