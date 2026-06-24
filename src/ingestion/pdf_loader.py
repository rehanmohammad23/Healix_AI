from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from src.config import DATA_RAW_DIR, CHUNK_SIZE, CHUNK_OVERLAP
from pathlib import Path
from loguru import logger

def load_and_chunk_pdfs():
    pdf_files = list(DATA_RAW_DIR.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"No PDFs found in {DATA_RAW_DIR}")
    
    logger.info(f"Found {len(pdf_files)} PDF(s): {[f.name for f in pdf_files]}")
    
    all_docs = []
    for pdf_path in pdf_files:
        logger.info(f"Loading: {pdf_path.name}")
        loader = PyMuPDFLoader(str(pdf_path))
        docs = loader.load()
        all_docs.extend(docs)
        logger.info(f"  → {len(docs)} pages loaded")
    
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""]
    )
    chunks = splitter.split_documents(all_docs)
    logger.info(f"Total chunks created: {len(chunks)}")
    return chunks