"""
Knowledge Base Service for Lean MVP Architecture
=================================================

Handles:
- PDF document ingestion and chunking
- Vector embedding storage in SQLite (replaces ChromaDB)
- Semantic search for RAG retrieval

Optimized for minimal dependencies and fast startup.
Upgrade path: Migrate to pgvector or Pinecone when >10K chunks.
"""
import os
import uuid
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

# PDF Parsing
import fitz  # PyMuPDF

# Lean MVP: Use SQLite vector store instead of ChromaDB
from services.vectors import vector_store, get_embedding

# Database
from sqlalchemy.orm import Session

# ============================================================================
# CONFIGURATION
# ============================================================================

CHUNK_SIZE = 500  # characters per chunk
CHUNK_OVERLAP = 50  # overlap between chunks

# Track initialization
_initialized = False


def init_chromadb():
    """
    Compatibility shim - initializes SQLite vector store.
    Kept for backward compatibility with existing code.
    """
    global _initialized
    if _initialized:
        return True
    
    try:
        # SQLite vector store auto-initializes
        stats = vector_store.get_stats()
        print(f"✅ SQLite Vector Store initialized. Chunks: {stats['chunks']}")
        _initialized = True
        return True
    except Exception as e:
        print(f"⚠️ Vector store initialization: {e}")
        _initialized = True  # Continue anyway, will create on first use
        return True


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
# EMBEDDING & VECTOR STORAGE (SQLite-based)
# ============================================================================

def add_chunks_to_chromadb(
    document_id: str,
    chunks: List[Dict[str, Any]],
    document_title: str = ""
) -> List[str]:
    """
    Add document chunks to SQLite vector store.
    Generates embeddings using available AI provider.
    Returns: list of chunk IDs
    """
    embedding_ids = []
    
    for chunk in chunks:
        chunk_content = chunk["content"]
        
        # Generate embedding
        try:
            embedding = get_embedding(chunk_content)
        except Exception as e:
            print(f"⚠️ Embedding generation failed, using fallback: {e}")
            embedding = get_embedding(chunk_content)  # Will use hash fallback
        
        # Store in SQLite vector store
        chunk_id = vector_store.add_chunk(
            document_id=document_id,
            content=chunk_content,
            embedding=embedding,
            chunk_index=chunk["chunk_index"],
            metadata={
                "document_title": document_title,
                "page": chunk.get("page", 0)
            }
        )
        
        embedding_ids.append(chunk_id)
    
    print(f"✅ Added {len(chunks)} chunks to SQLite vector store for document: {document_id}")
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
    if not _initialized:
        init_chromadb()
    
    try:
        # Generate query embedding
        query_embedding = get_embedding(query)
        
        # Search in SQLite vector store
        results = vector_store.search(
            query_embedding=query_embedding,
            top_k=n_results,
            threshold=0.5  # Lower threshold for hash-based fallback embeddings
        )
        
        # Format results (compatible with ChromaDB format)
        formatted_results = []
        for result in results:
            formatted_results.append({
                "content": result["content"],
                "id": result["chunk_id"],
                "metadata": {
                    "document_title": result.get("document_title", ""),
                    **result.get("metadata", {})
                },
                "distance": 1 - result["similarity"]  # Convert similarity to distance
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
    3. Store chunks in SQLite vector store
    4. Record in database (if session provided)
    
    Returns: document metadata dict
    """
    from models import KnowledgeDocument, KnowledgeChunk
    
    document_id = str(uuid.uuid4())
    
    try:
        # Add document to vector store
        vector_store.add_document(
            title=title or filename,
            content=f"Document: {filename}",
            metadata={"description": description}
        )
        
        # 1. Extract text
        print(f"📄 Extracting text from: {filename}")
        pages = extract_text_with_pages(pdf_path)
        total_pages = len(pages)
        
        # 2. Chunk the text
        print(f"✂️ Chunking {total_pages} pages...")
        chunks = chunk_pages(pages)
        
        # 3. Store in SQLite vector store
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
            from models import KnowledgeDocument
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
    if not _initialized:
        init_chromadb()
    
    vector_stats = vector_store.get_stats()
    
    return {
        "chromadb_initialized": True,  # Compatibility flag
        "vector_store": "sqlite",  # Lean MVP
        "total_chunks": vector_stats["chunks"],
        "total_documents": vector_stats["documents"],
        "embedded_chunks": vector_stats["embedded_chunks"],
        "db_size_bytes": vector_stats["db_size_bytes"],
        "collection_name": "resort_knowledge"
    }


# Initialize on module load
init_chromadb()
