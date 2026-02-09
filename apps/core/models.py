from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Text, Integer, Float, Boolean
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime
import uuid

Base = declarative_base()


# ============================================================================
# PHASE 4: User Authentication Model
# ============================================================================

class UserModel(Base):
    """Staff users for authentication and RBAC."""
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    name = Column(String, nullable=True)
    
    # RBAC
    role = Column(String, default="front_desk_agent")  # super_admin, resort_manager, front_desk_agent, readonly
    permissions = Column(JSON, default=list)  # Additional granular permissions
    
    # Multi-tenancy
    resort_id = Column(String, nullable=True, index=True)  # NULL = all resorts access
    
    # Security tracking
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime, nullable=True)
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    password_changed_at = Column(DateTime, default=datetime.utcnow)
    
    # Audit
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String, nullable=True)


class GuestModel(Base):
    __tablename__ = "guests"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    # Store channel_ids as JSON: {"whatsapp": "+123", "line": "U123"}
    channel_ids = Column(JSON, default=dict) 
    language = Column(String, default="en")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # PHASE 4: GDPR/PDPA Compliance Fields
    consent_marketing = Column(Boolean, default=False)
    consent_analytics = Column(Boolean, default=False)
    consent_timestamp = Column(DateTime, nullable=True)
    data_retention_days = Column(Integer, default=730)  # 2 years default
    deletion_requested_at = Column(DateTime, nullable=True)
    anonymized_at = Column(DateTime, nullable=True)
    data_exported_at = Column(DateTime, nullable=True)
    
    # Country for regional compliance (PDPA, GDPR, etc.)
    country_code = Column(String(2), nullable=True)  # ISO 3166-1 alpha-2
    
    messages = relationship("MessageModel", back_populates="guest")

class ThreadModel(Base):
    __tablename__ = "threads"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guest_id = Column(String, ForeignKey("guests.id"), nullable=True)
    status = Column(String, default="active") # active, closed, pending_agent
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # SLA Tracking fields
    last_guest_message = Column(DateTime, nullable=True)
    last_agent_reply = Column(DateTime, nullable=True)
    sla_status = Column(String, default="green")  # green, yellow, red
    sla_breached = Column(Boolean, default=False)
    
    messages = relationship("MessageModel", back_populates="thread")

class MessageModel(Base):
    __tablename__ = "messages"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id = Column(String, ForeignKey("threads.id"), nullable=True)
    guest_id = Column(String, ForeignKey("guests.id"), nullable=True)
    
    channel = Column(String) # whatsapp, line, etc
    direction = Column(String) # inbound, outbound
    sender_id = Column(String)
    
    # Store simplified content
    content_type = Column(String) # text, image
    body = Column(Text)
    media_url = Column(String, nullable=True)
    metadata_json = Column(JSON, default=dict)
    
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # PHASE 4: PII tracking
    contains_pii = Column(Boolean, default=False)
    pii_categories = Column(JSON, default=list)  # ["email", "phone", "address"]
    
    guest = relationship("GuestModel", back_populates="messages")
    thread = relationship("ThreadModel", back_populates="messages")


# ============================================================================
# PHASE 3: Knowledge Base Models
# ============================================================================

class KnowledgeDocument(Base):
    """Tracks uploaded SOPs and knowledge documents."""
    __tablename__ = "knowledge_documents"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String, nullable=False)
    file_type = Column(String, default="pdf")  # pdf, txt, md
    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    
    # Processing metadata
    total_chunks = Column(Integer, default=0)
    total_pages = Column(Integer, default=0)
    status = Column(String, default="pending")  # pending, processing, ready, error
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)
    
    chunks = relationship("KnowledgeChunk", back_populates="document")


class KnowledgeChunk(Base):
    """Individual chunks of knowledge documents for RAG retrieval."""
    __tablename__ = "knowledge_chunks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, ForeignKey("knowledge_documents.id"), nullable=False)
    
    # Content
    content = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=True)
    
    # Embedding info (stored in ChromaDB, but we track metadata here)
    embedding_id = Column(String, nullable=True)  # ChromaDB ID
    token_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    document = relationship("KnowledgeDocument", back_populates="chunks")


class CopilotSuggestion(Base):
    """Tracks AI suggestions for analytics and feedback."""
    __tablename__ = "copilot_suggestions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id = Column(String, ForeignKey("threads.id"), nullable=True)
    message_id = Column(String, ForeignKey("messages.id"), nullable=True)
    
    # Suggestion content
    suggestion_text = Column(Text, nullable=False)
    confidence = Column(Float, default=0.0)
    
    # Context used
    source_chunks = Column(JSON, default=list)  # List of chunk IDs used
    
    # Agent feedback
    was_used = Column(Boolean, nullable=True)
    agent_rating = Column(Integer, nullable=True)  # 1-5 rating
    
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================================================
# PHASE 4: Compliance & Audit Models
# ============================================================================

class DataDeletionRequest(Base):
    """Tracks GDPR/PDPA data deletion (right to be forgotten) requests."""
    __tablename__ = "data_deletion_requests"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guest_id = Column(String, ForeignKey("guests.id"), nullable=False)
    
    # Request details
    request_type = Column(String, default="deletion")  # deletion, export, anonymization
    reason = Column(Text, nullable=True)
    requester_email = Column(String, nullable=True)
    
    # Processing
    status = Column(String, default="pending")  # pending, processing, completed, rejected
    processed_at = Column(DateTime, nullable=True)
    processed_by = Column(String, nullable=True)  # User ID who processed
    
    # Compliance tracking
    deadline = Column(DateTime, nullable=True)  # GDPR: 30 days
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)


class ConsentLog(Base):
    """Audit log for consent changes (GDPR Article 7 compliance)."""
    __tablename__ = "consent_logs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    guest_id = Column(String, ForeignKey("guests.id"), nullable=False)
    
    consent_type = Column(String, nullable=False)  # marketing, analytics, necessary
    action = Column(String, nullable=False)  # granted, withdrawn
    previous_value = Column(Boolean, nullable=True)
    new_value = Column(Boolean, nullable=False)
    
    # Context
    source = Column(String, default="system")  # system, user_request, api
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)


