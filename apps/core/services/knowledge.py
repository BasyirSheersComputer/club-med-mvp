"""
Knowledge Base Service for Phase 3: The Copilot
================================================

Handles:
- PDF document ingestion and chunking
- Vector embedding storage in ChromaDB
- Semantic search for RAG retrieval
"""
import os
import uuid
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

# PDF Parsing
import fitz  # PyMuPDF

# Vector DB
import chromadb
from chromadb.config import Settings

# Database
from sqlalchemy.orm import Session

# ============================================================================
# CONFIGURATION
# ============================================================================

CHUNK_SIZE = 500  # characters per chunk
CHUNK_OVERLAP = 50  # overlap between chunks
CHROMA_PERSIST_PATH = "/app/data/chromadb"  # Persisted in volume

# Initialize ChromaDB client
chroma_client = None
knowledge_collection = None

def init_chromadb():
    """Initialize ChromaDB with persistent storage."""
    global chroma_client, knowledge_collection
    
    try:
        # Ensure directory exists
        os.makedirs(CHROMA_PERSIST_PATH, exist_ok=True)
        
        chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_PATH)
        
        # Get or create the knowledge collection
        knowledge_collection = chroma_client.get_or_create_collection(
            name="resort_knowledge",
            metadata={"description": "Club Med SOPs and knowledge base"}
        )
        
        print(f"✅ ChromaDB initialized. Collection: resort_knowledge ({knowledge_collection.count()} documents)")
        return True
    except Exception as e:
        print(f"❌ ChromaDB initialization failed: {e}")
        return False


# ============================================================================
# PDF PARSING & CHUNKING
# ============================================================================

def extract_text_from_pdf(pdf_path: str) -> Tuple[str, int]:
    """
    Extract all text from a PDF file.
    Returns: (full_text, page_count)
    """
    try:
        doc = fitz.open(pdf_path)
        full_text = ""
        
        for page in doc:
            full_text += page.get_text() + "\n"
        
        page_count = len(doc)
        doc.close()
        
        return full_text.strip(), page_count
    except Exception as e:
        print(f"❌ PDF extraction error: {e}")
        raise


def extract_text_with_pages(pdf_path: str) -> List[Dict[str, Any]]:
    """
    Extract text from PDF with page numbers preserved.
    Returns list of: {"page": int, "content": str}
    """
    try:
        doc = fitz.open(pdf_path)
        pages = []
        
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            if text:
                pages.append({
                    "page": page_num,
                    "content": text
                })
        
        doc.close()
        return pages
    except Exception as e:
        print(f"❌ PDF page extraction error: {e}")
        raise


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """
    Split text into overlapping chunks for better context preservation.
    """
    if not text:
        return []
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        # Try to find a natural break point (sentence end)
        if end < len(text):
            # Look for sentence-ending punctuation
            for punct in ['. ', '.\n', '! ', '!\n', '? ', '?\n']:
                last_punct = text.rfind(punct, start, end)
                if last_punct > start + chunk_size // 2:
                    end = last_punct + 1
                    break
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        start = end - overlap if end < len(text) else end
    
    return chunks


def chunk_pages(pages: List[Dict[str, Any]], chunk_size: int = CHUNK_SIZE) -> List[Dict[str, Any]]:
    """
    Chunk pages while preserving page number metadata.
    Returns: [{"content": str, "page": int, "chunk_index": int}]
    """
    all_chunks = []
    chunk_index = 0
    
    for page_data in pages:
        page_chunks = chunk_text(page_data["content"], chunk_size)
        
        for chunk_content in page_chunks:
            all_chunks.append({
                "content": chunk_content,
                "page": page_data["page"],
                "chunk_index": chunk_index
            })
            chunk_index += 1
    
    return all_chunks


# ============================================================================
# EMBEDDING & VECTOR STORAGE
# ============================================================================

def add_chunks_to_chromadb(
    document_id: str,
    chunks: List[Dict[str, Any]],
    document_title: str = ""
) -> List[str]:
    """
    Add document chunks to ChromaDB.
    ChromaDB will automatically generate embeddings using its default model.
    Returns: list of embedding IDs
    """
    if not knowledge_collection:
        init_chromadb()
    
    if not knowledge_collection:
        raise ValueError("ChromaDB not initialized")
    
    embedding_ids = []
    
    for chunk in chunks:
        embedding_id = f"{document_id}_{chunk['chunk_index']}"
        
        knowledge_collection.add(
            ids=[embedding_id],
            documents=[chunk["content"]],
            metadatas=[{
                "document_id": document_id,
                "document_title": document_title,
                "page": chunk.get("page", 0),
                "chunk_index": chunk["chunk_index"]
            }]
        )
        
        embedding_ids.append(embedding_id)
    
    print(f"✅ Added {len(chunks)} chunks to ChromaDB for document: {document_id}")
    return embedding_ids


def search_knowledge(
    query: str,
    n_results: int = 5,
    filter_document_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Semantic search in the knowledge base.
    Returns list of relevant chunks with metadata.
    """
    if not knowledge_collection:
        init_chromadb()
    
    if not knowledge_collection or knowledge_collection.count() == 0:
        return []
    
    where_filter = None
    if filter_document_id:
        where_filter = {"document_id": filter_document_id}
    
    try:
        results = knowledge_collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where_filter
        )
        
        # Format results
        formatted_results = []
        if results and results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                formatted_results.append({
                    "content": doc,
                    "id": results["ids"][0][i] if results["ids"] else None,
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results.get("distances") else None
                })
        
        return formatted_results
    except Exception as e:
        print(f"❌ Knowledge search error: {e}")
        return []


# ============================================================================
# DOCUMENT INGESTION PIPELINE
# ============================================================================

def ingest_pdf_document(
    pdf_path: str,
    filename: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    db: Optional[Session] = None
) -> Dict[str, Any]:
    """
    Full pipeline to ingest a PDF document:
    1. Extract text with page numbers
    2. Chunk the text
    3. Store chunks in ChromaDB
    4. Record in database (if session provided)
    
    Returns: document metadata dict
    """
    from models import KnowledgeDocument, KnowledgeChunk
    
    document_id = str(uuid.uuid4())
    
    try:
        # 1. Extract text
        print(f"📄 Extracting text from: {filename}")
        pages = extract_text_with_pages(pdf_path)
        total_pages = len(pages)
        
        # 2. Chunk the text
        print(f"✂️ Chunking {total_pages} pages...")
        chunks = chunk_pages(pages)
        
        # 3. Store in ChromaDB
        print(f"🔍 Storing {len(chunks)} chunks in vector DB...")
        embedding_ids = add_chunks_to_chromadb(
            document_id=document_id,
            chunks=chunks,
            document_title=title or filename
        )
        
        # 4. Record in database
        if db:
            doc_record = KnowledgeDocument(
                id=document_id,
                filename=filename,
                title=title or filename,
                description=description,
                total_chunks=len(chunks),
                total_pages=total_pages,
                status="ready",
                processed_at=datetime.utcnow()
            )
            db.add(doc_record)
            
            for i, chunk_data in enumerate(chunks):
                chunk_record = KnowledgeChunk(
                    document_id=document_id,
                    content=chunk_data["content"],
                    chunk_index=chunk_data["chunk_index"],
                    page_number=chunk_data.get("page"),
                    embedding_id=embedding_ids[i] if i < len(embedding_ids) else None,
                    token_count=len(chunk_data["content"]) // 4  # Approximate
                )
                db.add(chunk_record)
            
            db.commit()
            print(f"✅ Document recorded in database: {document_id}")
        
        return {
            "document_id": document_id,
            "filename": filename,
            "title": title or filename,
            "total_pages": total_pages,
            "total_chunks": len(chunks),
            "status": "ready"
        }
        
    except Exception as e:
        print(f"❌ Document ingestion failed: {e}")
        
        if db:
            error_doc = KnowledgeDocument(
                id=document_id,
                filename=filename,
                title=title or filename,
                status="error",
                error_message=str(e)
            )
            db.add(error_doc)
            db.commit()
        
        return {
            "document_id": document_id,
            "filename": filename,
            "status": "error",
            "error": str(e)
        }


def get_knowledge_stats() -> Dict[str, Any]:
    """Get statistics about the knowledge base."""
    if not knowledge_collection:
        init_chromadb()
    
    stats = {
        "chromadb_initialized": knowledge_collection is not None,
        "total_chunks": 0,
        "collection_name": "resort_knowledge"
    }
    
    if knowledge_collection:
        stats["total_chunks"] = knowledge_collection.count()
    
    return stats


# Initialize on module load
init_chromadb()
