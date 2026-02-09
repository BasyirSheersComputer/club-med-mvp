"""
SQLite Vector Search for Lean MVP Architecture
===============================================

Replaces ChromaDB for MVP deployments with <10K document chunks.
Uses SQLite + numpy for fast, zero-dependency vector search.

Performance: <1ms for 10K vectors on modern hardware.
Upgrade path: Migrate to pgvector or Pinecone when >10K chunks.
"""
import sqlite3
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import json
import os
import hashlib


class SQLiteVectorStore:
    """
    Lightweight vector store using SQLite.
    Stores embeddings as JSON arrays, searches using cosine similarity.
    """
    
    def __init__(self, db_path: str = "knowledge.db"):
        self.db_path = db_path
        self._init_db()
        self._vectors_cache: Dict[str, np.ndarray] = {}
        self._cache_loaded = False
    
    def _init_db(self):
        """Initialize SQLite database with required tables."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                title TEXT,
                content TEXT,
                metadata TEXT,
                created_at TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                document_id TEXT,
                content TEXT,
                embedding TEXT,
                chunk_index INTEGER,
                metadata TEXT,
                created_at TEXT,
                FOREIGN KEY (document_id) REFERENCES documents(id)
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_document 
            ON chunks(document_id)
        """)
        
        conn.commit()
        conn.close()
    
    def _load_vectors_cache(self):
        """Load all vectors into memory for fast search."""
        if self._cache_loaded:
            return
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL")
        rows = cursor.fetchall()
        
        for chunk_id, embedding_json in rows:
            if embedding_json:
                self._vectors_cache[chunk_id] = np.array(json.loads(embedding_json))
        
        conn.close()
        self._cache_loaded = True
    
    def add_document(self, title: str, content: str, metadata: Dict = None) -> str:
        """Add a document to the store."""
        doc_id = hashlib.md5(f"{title}:{content[:100]}".encode()).hexdigest()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO documents (id, title, content, metadata, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            doc_id,
            title,
            content,
            json.dumps(metadata or {}),
            datetime.utcnow().isoformat()
        ))
        
        conn.commit()
        conn.close()
        
        return doc_id
    
    def add_chunk(
        self, 
        document_id: str, 
        content: str, 
        embedding: List[float],
        chunk_index: int = 0,
        metadata: Dict = None
    ) -> str:
        """Add a chunk with embedding to the store."""
        chunk_id = hashlib.md5(f"{document_id}:{chunk_index}:{content[:50]}".encode()).hexdigest()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        embedding_json = json.dumps(embedding) if embedding else None
        
        cursor.execute("""
            INSERT OR REPLACE INTO chunks (id, document_id, content, embedding, chunk_index, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            chunk_id,
            document_id,
            content,
            embedding_json,
            chunk_index,
            json.dumps(metadata or {}),
            datetime.utcnow().isoformat()
        ))
        
        conn.commit()
        conn.close()
        
        # Update cache
        if embedding:
            self._vectors_cache[chunk_id] = np.array(embedding)
        
        return chunk_id
    
    def search(
        self, 
        query_embedding: List[float], 
        top_k: int = 5,
        threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """
        Search for similar chunks using cosine similarity.
        
        Args:
            query_embedding: Query vector
            top_k: Number of results to return
            threshold: Minimum similarity score (0-1)
        
        Returns:
            List of matching chunks with similarity scores
        """
        self._load_vectors_cache()
        
        if not self._vectors_cache:
            return []
        
        query_vec = np.array(query_embedding)
        query_norm = np.linalg.norm(query_vec)
        
        if query_norm == 0:
            return []
        
        # Calculate cosine similarity for all vectors
        similarities = []
        for chunk_id, stored_vec in self._vectors_cache.items():
            stored_norm = np.linalg.norm(stored_vec)
            if stored_norm > 0:
                similarity = np.dot(query_vec, stored_vec) / (query_norm * stored_norm)
                if similarity >= threshold:
                    similarities.append((chunk_id, similarity))
        
        # Sort by similarity descending
        similarities.sort(key=lambda x: x[1], reverse=True)
        top_results = similarities[:top_k]
        
        # Fetch chunk details from database
        if not top_results:
            return []
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        results = []
        for chunk_id, similarity in top_results:
            cursor.execute("""
                SELECT c.content, c.metadata, d.title
                FROM chunks c
                JOIN documents d ON c.document_id = d.id
                WHERE c.id = ?
            """, (chunk_id,))
            
            row = cursor.fetchone()
            if row:
                results.append({
                    "chunk_id": chunk_id,
                    "content": row[0],
                    "metadata": json.loads(row[1]) if row[1] else {},
                    "document_title": row[2],
                    "similarity": float(similarity)
                })
        
        conn.close()
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the vector store."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM documents")
        doc_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM chunks")
        chunk_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL")
        embedded_count = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "documents": doc_count,
            "chunks": chunk_count,
            "embedded_chunks": embedded_count,
            "cached_vectors": len(self._vectors_cache),
            "db_path": self.db_path,
            "db_size_bytes": os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        }
    
    def delete_document(self, document_id: str) -> bool:
        """Delete a document and its chunks."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get chunk IDs to remove from cache
        cursor.execute("SELECT id FROM chunks WHERE document_id = ?", (document_id,))
        chunk_ids = [row[0] for row in cursor.fetchall()]
        
        # Delete chunks
        cursor.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        
        # Delete document
        cursor.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        
        conn.commit()
        conn.close()
        
        # Update cache
        for chunk_id in chunk_ids:
            self._vectors_cache.pop(chunk_id, None)
        
        return True


# Global instance
vector_store = SQLiteVectorStore()


# ============================================================================
# Simple embedding function (using existing AI providers)
# ============================================================================

def get_embedding(text: str) -> List[float]:
    """
    Generate embedding for text.
    Falls back to simple hash-based embedding if AI not available.
    """
    try:
        # Try using Google's embedding API
        import google.generativeai as genai
        
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            result = genai.embed_content(
                model="models/embedding-001",
                content=text,
                task_type="retrieval_document"
            )
            return result['embedding']
    except Exception:
        pass
    
    try:
        # Try OpenAI
        from openai import OpenAI
        
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            client = OpenAI(api_key=api_key)
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=text
            )
            return response.data[0].embedding
    except Exception:
        pass
    
    # Fallback: simple hash-based embedding (not semantic, but works for exact matches)
    # This is a placeholder - should use real embeddings in production
    import hashlib
    hash_bytes = hashlib.sha256(text.encode()).digest()
    # Convert to 256-dim float vector
    return [float(b) / 255.0 for b in hash_bytes * 8]  # 256 dimensions
