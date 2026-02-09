import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import socketio
import os
import redis
import psycopg2
from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, GuestModel, MessageModel, ThreadModel
from services.translation import process_message_translation, get_usage_stats, reset_provider, AIProvider
import json

# Phase 4: Security, Observability, and Resilience imports
from services.security import (
    create_access_token, create_refresh_token, verify_token, refresh_access_token,
    logout, Role, Permission, has_permission, check_rate_limit,
    log_audit_event, get_security_stats, sanitize_input
)
from services.observability import (
    metrics, logger, correlation_id_var,
    get_observability_dashboard, check_alerts, HealthStatus
)
from services.resilience import (
    get_resilience_stats, get_all_circuit_breakers, get_circuit_breaker,
    get_dlq, DegradationMode, set_degradation_mode, get_degradation_mode,
    FallbackResponse
)

# Configuration
DB_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/resortos")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

# Socket.IO Setup
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
socket_app = socketio.ASGIApp(sio)

# DB Setup
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create Tables (Simplified Migration)
try:
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created/verified.")
except Exception as e:
    print(f"❌ Database Schema Error: {e}")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Logic to Process & Persist Event
def process_event(event_data: str):
    try:
        data = json.loads(event_data)
        # Check if it's a UnifiedMessage (has 'channel', 'content', 'guest')
        if "channel" not in data or "guest" not in data:
            print("⚠️ Skipping non-message event")
            return
            
        db = SessionLocal()
        
        # 1. Find or Create Guest
        guest_info = data.get("guest")
        sender_id = data.get("sender_id")
        channel = data.get("channel")
        
        # Simple lookup by channel_ids (JSONB query would be better, but MVP assumes string/dict match)
        # For MVP, we'll do a naive search or create
        # In prod: Use unique constraint on channel_ids->>'whatsapp'
        
        existing_guest = None
        # Optimization: We should query by channel_ids in a real implementation
        # For now, let's just create a new guest if we don't have a reliable ID 
        # (This is a simplification. In reality we need to search first)
        
        # Let's try to query all guests and find match in Python (inefficient but safe for <100 guests MVP)
        # TODO: Replace with PG JSONB query
        all_guests = db.query(GuestModel).all()
        for g in all_guests:
            if g.channel_ids and g.channel_ids.get(channel) == sender_id:
                existing_guest = g
                break
        
        if not existing_guest:
            new_guest = GuestModel(
                name=guest_info.get("name", "Unknown"),
                channel_ids={channel: sender_id}
            )
            db.add(new_guest)
            db.commit()
            db.refresh(new_guest)
            existing_guest = new_guest
            print(f"👤 Created new Guest: {existing_guest.id}")
        else:
            print(f"👤 Found existing Guest: {existing_guest.id}")
            
        # 2. Translate Message (if text content)
        content = data.get("content", {})
        original_body = content.get("body", "")
        translated_body = original_body
        detected_language = existing_guest.language or "en"
        
        if content.get("type") == "text" and original_body:
            try:
                translation_result = process_message_translation(
                    original_body, 
                    guest_language=None  # Auto-detect
                )
                translated_body = translation_result.get("translated_text", original_body)
                detected_language = translation_result.get("detected_language", "en")
                
                # Update guest language if detected
                if existing_guest.language != detected_language:
                    existing_guest.language = detected_language
                    db.commit()
                    print(f"🌐 Updated Guest language: {detected_language}")
            except Exception as e:
                print(f"⚠️ Translation skipped: {e}")
        
        # 3. Persist Message with translation
        new_msg = MessageModel(
            channel=channel,
            direction=data.get("direction"),
            sender_id=sender_id,
            content_type=content.get("type"),
            body=original_body,
            guest_id=existing_guest.id
        )
        # Store translated text in metadata
        new_msg.metadata_json = {
            "translated_text": translated_body,
            "source_language": detected_language,
            "target_language": "en"
        }
        db.add(new_msg)
        db.commit()
        print(f"💾 Persisted Message: {new_msg.id}")
        
        return new_msg
        
    except Exception as e:
        print(f"❌ Processing Error: {e}")
    finally:
        db.close()

# Background Task for Redis Subscription
async def redis_listener():
    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        pubsub = r.pubsub()
        await asyncio.to_thread(pubsub.subscribe, "events")
        
        print("🎧 Core Service: Listening for events on 'events' channel...")
        
        while True:
            message = await asyncio.to_thread(pubsub.get_message, ignore_subscribe_messages=True)
            if message:
                print(f"📥 Received Event: {message['data']}")
                
                # Sync processing for MVP
                # In prod, push to Celery/background worker
                await asyncio.to_thread(process_event, message['data'])
                
                # Emit to frontend via Socket.io
                await sio.emit('new_message', data=message['data'])
            await asyncio.sleep(0.01)
    except Exception as e:
        print(f"❌ Redis Listener Error: {str(e)}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    task = asyncio.create_task(redis_listener())
    yield
    # Shutdown
    task.cancel()

app = FastAPI(title="ResortOS Core", version="0.1.0", lifespan=lifespan)

# Mount Socket.IO to /socket.io
app.mount("/socket.io", socket_app)

# Configuration
DB_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/resortos")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

@app.get("/")
def health_check():
    return {"status": "ok", "service": "core"}

@app.get("/health/deep")
def deep_health_check():
    checks = {}
    
    # Check PostgreSQL
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        checks["database"] = "connected"
        conn.close()
    except Exception as e:
        checks["database"] = f"failed: {str(e)}"
        
    # Check Redis
    try:
        r = redis.from_url(REDIS_URL)
        r.ping()
        checks["redis"] = "connected"
    except Exception as e:
        checks["redis"] = f"failed: {str(e)}"
    
    if any("failed" in v for v in checks.values()):
        raise HTTPException(status_code=503, detail=checks)
        
    return {"status": "healthy", "checks": checks}


@app.get("/ai/usage")
def get_ai_usage():
    """Get AI provider usage statistics and monitoring data."""
    return get_usage_stats()


@app.post("/ai/reset/{provider}")
def reset_ai_provider(provider: str):
    """
    Re-enable a disabled AI provider.
    Use when provider issues are resolved and you want to retry.
    """
    try:
        if provider == "gemini":
            reset_provider(AIProvider.GEMINI)
            return {"status": "ok", "message": "Gemini provider reset"}
        elif provider == "openai":
            reset_provider(AIProvider.OPENAI)
            return {"status": "ok", "message": "OpenAI provider reset"}
        else:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# PHASE 3: COPILOT ENDPOINTS
# ============================================================================

from pydantic import BaseModel
from typing import Optional, List
import tempfile
import shutil
from fastapi import UploadFile, File

# Import Phase 3 services
from services.copilot import generate_smart_reply, get_copilot_stats, record_suggestion_feedback
from services.sla import get_sla_stats, calculate_sla_status, SLAMonitor
from services.knowledge import (
    ingest_pdf_document, search_knowledge, get_knowledge_stats, init_chromadb
)


class SuggestRequest(BaseModel):
    """Request model for smart reply suggestions."""
    message: str
    thread_id: Optional[str] = None
    channel: str = "whatsapp"
    language: str = "en"
    include_knowledge: bool = True


class SuggestionFeedback(BaseModel):
    """Feedback on a copilot suggestion."""
    suggestion_id: str
    was_used: bool
    rating: Optional[int] = None  # 1-5


@app.post("/copilot/suggest")
def copilot_suggest(request: SuggestRequest):
    """
    Generate a smart reply suggestion using RAG.
    Retrieves relevant SOPs and generates context-aware response.
    """
    try:
        # Get conversation history if thread_id provided
        conversation_history = []
        if request.thread_id:
            db = SessionLocal()
            try:
                messages = db.query(MessageModel).filter(
                    MessageModel.thread_id == request.thread_id
                ).order_by(MessageModel.timestamp.desc()).limit(10).all()
                
                conversation_history = [
                    {"direction": m.direction, "body": m.body}
                    for m in reversed(messages)
                ]
            finally:
                db.close()
        
        result = generate_smart_reply(
            guest_message=request.message,
            conversation_history=conversation_history,
            channel=request.channel,
            language=request.language,
            include_knowledge=request.include_knowledge
        )
        
        return {
            "suggestion": result.get("suggestion", ""),
            "confidence": result.get("confidence", 0.0),
            "provider": result.get("provider_used", "none"),
            "knowledge_context": result.get("knowledge_chunks_available", 0) > 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/copilot/feedback")
def copilot_feedback(feedback: SuggestionFeedback):
    """
    Record feedback on a copilot suggestion.
    Used to improve suggestion quality over time.
    """
    db = SessionLocal()
    try:
        success = record_suggestion_feedback(
            suggestion_id=feedback.suggestion_id,
            was_used=feedback.was_used,
            rating=feedback.rating,
            db=db
        )
        return {"recorded": success}
    finally:
        db.close()


@app.get("/copilot/stats")
def copilot_statistics():
    """
    Get Copilot usage and knowledge base statistics.
    """
    db = SessionLocal()
    try:
        return get_copilot_stats(db)
    finally:
        db.close()


# ============================================================================
# PHASE 3: KNOWLEDGE BASE ENDPOINTS
# ============================================================================

@app.post("/knowledge/upload")
async def upload_knowledge_document(
    file: UploadFile = File(...),
    title: Optional[str] = None,
    description: Optional[str] = None
):
    """
    Upload a PDF document to the knowledge base.
    Document will be chunked, embedded, and stored in ChromaDB.
    """
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    
    # Save uploaded file temporarily
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name
        
        db = SessionLocal()
        try:
            result = ingest_pdf_document(
                pdf_path=tmp_path,
                filename=file.filename,
                title=title or file.filename,
                description=description,
                db=db
            )
            return result
        finally:
            db.close()
    finally:
        # Cleanup temp file
        if 'tmp_path' in locals():
            try:
                os.unlink(tmp_path)
            except:
                pass


@app.get("/knowledge/search")
def search_knowledge_base(query: str, top_k: int = 5):
    """
    Search the knowledge base for relevant information.
    Returns top-k most relevant chunks.
    """
    results = search_knowledge(query, n_results=top_k)
    return {
        "query": query,
        "results": results,
        "count": len(results)
    }


@app.get("/knowledge/stats")
def knowledge_statistics():
    """
    Get knowledge base statistics.
    """
    return get_knowledge_stats()


# ============================================================================
# PHASE 3: SLA MONITORING ENDPOINTS
# ============================================================================

@app.get("/sla/stats")
def sla_statistics():
    """
    Get SLA compliance statistics for active threads.
    """
    db = SessionLocal()
    try:
        return get_sla_stats(db)
    finally:
        db.close()


@app.get("/sla/thread/{thread_id}")
def thread_sla_status(thread_id: str):
    """
    Get SLA status for a specific thread.
    """
    db = SessionLocal()
    try:
        thread = db.query(ThreadModel).filter(ThreadModel.id == thread_id).first()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        sla_info = calculate_sla_status(
            thread.last_guest_message,
            thread.last_agent_reply
        )
        
        return {
            "thread_id": thread_id,
            **sla_info
        }
    finally:
        db.close()


# ============================================================================
# PHASE 3: COPILOT DASHBOARD ENDPOINT
# ============================================================================

@app.get("/copilot/dashboard")
def copilot_dashboard():
    """
    Get comprehensive dashboard data for the Copilot UI.
    Combines SLA, knowledge, and suggestion stats.
    """
    db = SessionLocal()
    try:
        return {
            "sla": get_sla_stats(db),
            "copilot": get_copilot_stats(db),
            "knowledge": get_knowledge_stats()
        }
    finally:
        db.close()


# ============================================================================
# PHASE 4: ENTERPRISE ROBUSTNESS ENDPOINTS
# ============================================================================

# -- Authentication Endpoints --

from pydantic import BaseModel
from typing import Optional

class LoginRequest(BaseModel):
    username: str
    password: str
    resort_id: Optional[str] = None

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900  # 15 minutes

class RefreshRequest(BaseModel):
    refresh_token: str


@app.post("/auth/login")
def login(request: LoginRequest):
    """
    Authenticate user and return JWT tokens.
    
    For demo purposes, accepts any username/password.
    In production, validate against user database.
    """
    # Demo authentication (replace with real auth in production)
    demo_users = {
        "admin": {"role": Role.SUPER_ADMIN, "name": "Admin User"},
        "manager": {"role": Role.RESORT_MANAGER, "name": "Resort Manager"},
        "agent": {"role": Role.FRONT_DESK_AGENT, "name": "Front Desk Agent"},
        "viewer": {"role": Role.READONLY, "name": "View Only User"}
    }
    
    user_info = demo_users.get(request.username.lower())
    if not user_info:
        # For demo, default to front desk agent
        user_info = {"role": Role.FRONT_DESK_AGENT, "name": request.username}
    
    user_id = f"user_{request.username.lower()}"
    
    access_token = create_access_token(
        user_id=user_id,
        role=user_info["role"],
        resort_id=request.resort_id,
        extra_claims={"name": user_info["name"]}
    )
    
    refresh_token = create_refresh_token(user_id, user_info["role"])
    
    log_audit_event(
        action="login",
        user_id=user_id,
        resource_type="auth",
        details={"username": request.username, "role": user_info["role"].value}
    )
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token
    )


@app.post("/auth/refresh")
def refresh_token(request: RefreshRequest):
    """
    Refresh access token using refresh token.
    Implements token rotation for security.
    """
    tokens = refresh_access_token(request.refresh_token)
    
    if not tokens:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    
    return TokenResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"]
    )


@app.post("/auth/logout")
def auth_logout(authorization: str = None):
    """
    Logout user and invalidate tokens.
    """
    if authorization:
        token = authorization.replace("Bearer ", "")
        logout(token)
    
    return {"status": "ok", "message": "Logged out successfully"}


@app.get("/auth/me")
def get_current_user_info(authorization: str = None):
    """
    Get current user info from JWT token.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="No token provided")
    
    token = authorization.replace("Bearer ", "")
    payload = verify_token(token)
    
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return {
        "user_id": payload.get("sub"),
        "role": payload.get("role"),
        "permissions": payload.get("permissions", []),
        "resort_id": payload.get("resort_id"),
        "name": payload.get("name")
    }


# -- Observability Endpoints --

@app.get("/metrics")
def get_metrics():
    """
    Get golden signals metrics (Prometheus-compatible).
    """
    return metrics.get_golden_signals()


@app.get("/metrics/latency")
def get_latency_metrics():
    """
    Get detailed latency metrics by endpoint.
    """
    return metrics.get_latency_stats()


@app.get("/observability/dashboard")
def observability_dashboard():
    """
    Get comprehensive observability dashboard data.
    Includes golden signals, alerts, and health status.
    """
    return get_observability_dashboard()


@app.get("/alerts")
def get_active_alerts():
    """
    Get currently active alerts based on thresholds.
    """
    return {
        "alerts": check_alerts(),
        "count": len(check_alerts())
    }


# -- Resilience Endpoints --

@app.get("/resilience/status")
def get_resilience_status():
    """
    Get resilience infrastructure status.
    Includes circuit breakers, DLQs, and degradation mode.
    """
    return get_resilience_stats()


@app.get("/resilience/circuit-breakers")
def list_circuit_breakers():
    """
    Get status of all circuit breakers.
    """
    return get_all_circuit_breakers()


@app.post("/resilience/degradation/{mode}")
def set_degradation(mode: str):
    """
    Set system degradation mode.
    
    Modes:
    - normal: Full functionality
    - read_only: Reject write operations
    - offline: Minimal operations only
    """
    mode_map = {
        "normal": DegradationMode.NORMAL,
        "read_only": DegradationMode.READ_ONLY,
        "offline": DegradationMode.OFFLINE
    }
    
    if mode not in mode_map:
        raise HTTPException(status_code=400, detail=f"Invalid mode. Use: {list(mode_map.keys())}")
    
    set_degradation_mode(mode_map[mode])
    
    log_audit_event(
        action="set_degradation_mode",
        user_id="system",
        resource_type="resilience",
        details={"mode": mode}
    )
    
    return {"status": "ok", "mode": mode}


@app.get("/resilience/dlq/{queue_name}")
def get_dlq_status(queue_name: str):
    """
    Get dead letter queue status and messages.
    """
    dlq = get_dlq(queue_name)
    return {
        "stats": dlq.get_stats(),
        "messages": dlq.get_all()[:50]  # Limit to 50 messages
    }


# -- Security Endpoints --

@app.get("/security/stats")
def security_statistics():
    """
    Get security service statistics.
    """
    return get_security_stats()


@app.get("/audit/log")
def get_audit_log_entries(
    limit: int = 100,
    user_id: Optional[str] = None,
    resource_type: Optional[str] = None
):
    """
    Get audit log entries for compliance.
    """
    from services.security import get_audit_log
    
    return {
        "entries": get_audit_log(
            user_id=user_id,
            resource_type=resource_type,
            limit=limit
        )
    }


# -- Enhanced Health Check --

@app.get("/health/deep")
def deep_health_check():
    """
    Deep health check with dependency verification.
    Checks database, Redis, AI providers, and Circuit Breakers.
    """
    checks = {}
    overall_status = "healthy"
    
    # Database check
    try:
        db = SessionLocal()
        db.execute("SELECT 1")
        checks["database"] = {"status": "healthy"}
        db.close()
    except Exception as e:
        checks["database"] = {"status": "unhealthy", "error": str(e)[:100]}
        overall_status = "unhealthy"
    
    # Redis check
    try:
        r = redis.from_url(REDIS_URL)
        r.ping()
        checks["redis"] = {"status": "healthy"}
    except Exception as e:
        checks["redis"] = {"status": "unhealthy", "error": str(e)[:100]}
        overall_status = "degraded" if overall_status == "healthy" else overall_status
    
    # AI providers check
    try:
        ai_stats = get_usage_stats()
        active_providers = sum(1 for p in ai_stats.get("providers", {}).values() if p.get("enabled"))
        checks["ai_providers"] = {
            "status": "healthy" if active_providers > 0 else "degraded",
            "active_count": active_providers
        }
        if active_providers == 0:
            overall_status = "degraded" if overall_status == "healthy" else overall_status
    except Exception as e:
        checks["ai_providers"] = {"status": "unknown", "error": str(e)[:100]}
    
    # Circuit breakers check
    breakers = get_all_circuit_breakers()
    open_breakers = [name for name, status in breakers.items() if status.get("state") == "open"]
    checks["circuit_breakers"] = {
        "status": "degraded" if open_breakers else "healthy",
        "open_circuits": open_breakers
    }
    if open_breakers:
        overall_status = "degraded" if overall_status == "healthy" else overall_status
    
    # Degradation mode check
    deg_mode = get_degradation_mode()
    checks["degradation_mode"] = {
        "status": deg_mode.value,
        "healthy": deg_mode == DegradationMode.NORMAL
    }
    
    return {
        "status": overall_status,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": "2.0.0-phase4",
        "checks": checks,
        "alerts": check_alerts()
    }


# -- Rate Limit Info Endpoint --

@app.get("/rate-limit/status")
def get_rate_limit_status(x_api_key: Optional[str] = None, client_ip: str = "unknown"):
    """
    Check current rate limit status for an identifier.
    """
    identifier = x_api_key or client_ip
    result = check_rate_limit(identifier)
    result["identifier_prefix"] = identifier[:10] + "..."
    return result


# ============================================================================
# PHASE 4: GDPR/PDPA COMPLIANCE ENDPOINTS
# ============================================================================

from services.compliance import (
    detect_pii, mask_pii_in_text, anonymize_pii,
    export_guest_data, delete_guest_data, update_consent,
    get_consent_history, apply_retention_policy, get_compliance_status
)


@app.get("/compliance/status")
def compliance_status():
    """
    Get overall GDPR/PDPA compliance status.
    Includes pending requests, overdue items, and consent metrics.
    """
    db = SessionLocal()
    try:
        return get_compliance_status(db)
    finally:
        db.close()


@app.get("/compliance/guest/{guest_id}/export")
def export_guest(guest_id: str):
    """
    Export all guest data in portable format (GDPR Article 20).
    Returns machine-readable JSON with all guest data.
    """
    db = SessionLocal()
    try:
        log_audit_event(
            action="data_export",
            user_id="api",
            resource_type="guest",
            resource_id=guest_id
        )
        return export_guest_data(guest_id, db)
    finally:
        db.close()


class DeletionRequest(BaseModel):
    reason: Optional[str] = None
    hard_delete: bool = False


@app.post("/compliance/guest/{guest_id}/delete")
def delete_guest(guest_id: str, request: DeletionRequest):
    """
    Delete or anonymize guest data (GDPR Article 17 - Right to be Forgotten).
    
    Args:
        hard_delete: If true, permanently delete. If false, anonymize.
    """
    db = SessionLocal()
    try:
        log_audit_event(
            action="data_deletion" if request.hard_delete else "data_anonymization",
            user_id="api",
            resource_type="guest",
            resource_id=guest_id,
            details={"reason": request.reason}
        )
        result = delete_guest_data(
            guest_id, db,
            hard_delete=request.hard_delete,
            reason=request.reason
        )
        return result
    finally:
        db.close()


class ConsentUpdate(BaseModel):
    consent_type: str  # marketing, analytics
    granted: bool


@app.post("/compliance/guest/{guest_id}/consent")
def update_guest_consent(guest_id: str, consent: ConsentUpdate):
    """
    Update consent status for a guest.
    Creates audit trail for GDPR Article 7 compliance.
    """
    db = SessionLocal()
    try:
        result = update_consent(
            guest_id=guest_id,
            consent_type=consent.consent_type,
            granted=consent.granted,
            db=db,
            source="api"
        )
        return result
    finally:
        db.close()


@app.get("/compliance/guest/{guest_id}/consent/history")
def get_guest_consent_history(guest_id: str):
    """
    Get consent change history for audit compliance.
    """
    db = SessionLocal()
    try:
        return {"guest_id": guest_id, "history": get_consent_history(guest_id, db)}
    finally:
        db.close()


@app.post("/compliance/retention/apply")
def apply_data_retention(dry_run: bool = True):
    """
    Apply data retention policies to expired guest data.
    
    Args:
        dry_run: If true, only report what would be affected.
    """
    db = SessionLocal()
    try:
        log_audit_event(
            action="retention_policy_apply",
            user_id="system",
            resource_type="compliance",
            details={"dry_run": dry_run}
        )
        return apply_retention_policy(db, dry_run=dry_run)
    finally:
        db.close()


class PIICheckRequest(BaseModel):
    text: str


@app.post("/compliance/pii/detect")
def detect_pii_in_text(request: PIICheckRequest):
    """
    Detect PII categories in text.
    Returns list of detected PII types.
    """
    return detect_pii(request.text)


@app.post("/compliance/pii/mask")
def mask_pii_text(request: PIICheckRequest):
    """
    Mask all PII in text with placeholders.
    """
    return {
        "original_length": len(request.text),
        "masked_text": mask_pii_in_text(request.text)
    }


# ============================================================================
# PHASE 4: BACKUP & DISASTER RECOVERY ENDPOINTS
# ============================================================================

from services.backup import (
    export_database_snapshot, save_backup_to_file, list_backups,
    load_backup_from_file, cleanup_old_backups, restore_from_backup,
    get_backup_stats
)
from services.users import (
    create_user, authenticate_user, change_password,
    reset_password, deactivate_user, list_users
)


@app.get("/backup/stats")
def backup_statistics():
    """Get backup service statistics."""
    return get_backup_stats()


@app.get("/backup/list")
def list_all_backups():
    """List all available backups."""
    return {"backups": list_backups()}


@app.post("/backup/create")
def create_backup(include_messages: bool = True):
    """
    Create a new database backup.
    
    Args:
        include_messages: Whether to include message data (can be large)
    """
    db = SessionLocal()
    try:
        log_audit_event(
            action="backup_create",
            user_id="system",
            resource_type="backup"
        )
        snapshot = export_database_snapshot(db, include_messages=include_messages)
        result = save_backup_to_file(snapshot)
        return result
    finally:
        db.close()


@app.post("/backup/cleanup")
def cleanup_backups(max_age_days: int = 30):
    """
    Remove backups older than retention period.
    """
    log_audit_event(
        action="backup_cleanup",
        user_id="system",
        resource_type="backup",
        details={"max_age_days": max_age_days}
    )
    return cleanup_old_backups(max_age_days)


@app.post("/backup/restore")
def restore_backup(filepath: str, dry_run: bool = True):
    """
    Restore from a backup file.
    
    Args:
        filepath: Path to backup file
        dry_run: If true, only validate without making changes
    """
    db = SessionLocal()
    try:
        snapshot = load_backup_from_file(filepath)
        if not snapshot:
            raise HTTPException(status_code=404, detail="Backup file not found")
        
        log_audit_event(
            action="backup_restore",
            user_id="system",
            resource_type="backup",
            details={"filepath": filepath, "dry_run": dry_run}
        )
        
        return restore_from_backup(snapshot, db, dry_run=dry_run)
    finally:
        db.close()


# ============================================================================
# PHASE 4: USER MANAGEMENT ENDPOINTS
# ============================================================================

class CreateUserRequest(BaseModel):
    email: str
    password: str
    name: str
    role: str = "front_desk_agent"
    resort_id: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ResetPasswordRequest(BaseModel):
    new_password: str


@app.post("/users/create")
def create_new_user(request: CreateUserRequest):
    """
    Create a new staff user.
    """
    db = SessionLocal()
    try:
        result = create_user(
            email=request.email,
            password=request.password,
            name=request.name,
            role=request.role,
            resort_id=request.resort_id,
            db=db
        )
        
        if "error" not in result:
            log_audit_event(
                action="user_create",
                user_id="api",
                resource_type="user",
                resource_id=result.get("id")
            )
        
        return result
    finally:
        db.close()


@app.post("/users/authenticate")
def authenticate_staff_user(request: LoginRequest):
    """
    Authenticate a user with email and password.
    Returns user info if successful, includes lockout info.
    """
    db = SessionLocal()
    try:
        result = authenticate_user(request.username, request.password, db)
        
        if result.get("authenticated"):
            log_audit_event(
                action="user_login",
                user_id=result["user"]["id"],
                resource_type="auth"
            )
        
        return result
    finally:
        db.close()


@app.get("/users/list")
def list_all_users(resort_id: Optional[str] = None):
    """
    List all staff users.
    """
    db = SessionLocal()
    try:
        return {"users": list_users(db, resort_id=resort_id)}
    finally:
        db.close()


@app.post("/users/{user_id}/change-password")
def change_user_password(user_id: str, request: ChangePasswordRequest):
    """
    Change a user's password.
    """
    db = SessionLocal()
    try:
        result = change_password(
            user_id=user_id,
            current_password=request.current_password,
            new_password=request.new_password,
            db=db
        )
        
        if result.get("success"):
            log_audit_event(
                action="password_change",
                user_id=user_id,
                resource_type="user"
            )
        
        return result
    finally:
        db.close()


@app.post("/users/{user_id}/reset-password")
def admin_reset_password(user_id: str, request: ResetPasswordRequest):
    """
    Admin password reset.
    """
    db = SessionLocal()
    try:
        result = reset_password(user_id, request.new_password, db)
        
        if result.get("success"):
            log_audit_event(
                action="password_reset_admin",
                user_id=user_id,
                resource_type="user"
            )
        
        return result
    finally:
        db.close()


@app.post("/users/{user_id}/deactivate")
def deactivate_staff_user(user_id: str):
    """
    Deactivate a user account.
    """
    db = SessionLocal()
    try:
        result = deactivate_user(user_id, db)
        
        if result.get("success"):
            log_audit_event(
                action="user_deactivate",
                user_id=user_id,
                resource_type="user"
            )
        
        return result
    finally:
        db.close()


# ============================================================================
# PHASE 4: CACHING, TRACING, PERFORMANCE & SECRETS ENDPOINTS
# ============================================================================

from services.caching import cache, warm_guest_cache
from services.tracing import (
    get_recent_traces, get_trace_by_id, get_tracing_stats,
    clear_trace_buffer
)
from services.performance import (
    get_performance_stats, get_budget_violations, clear_performance_data
)
from services.secrets import get_secrets_status, get_secret_access_log


# -- Caching Endpoints --

@app.get("/cache/stats")
def cache_statistics():
    """Get multi-layer cache statistics (L1 memory + L2 Redis)."""
    return cache.get_stats()


@app.post("/cache/invalidate")
def invalidate_cache(pattern: Optional[str] = None):
    """
    Invalidate cache entries.
    
    Args:
        pattern: Redis key pattern to invalidate, or None for all.
    """
    if pattern:
        count = cache.invalidate_pattern(pattern)
        return {"invalidated_count": count, "pattern": pattern}
    else:
        cache.l1.clear()
        return {"message": "L1 cache cleared"}


class CacheWarmRequest(BaseModel):
    guest_ids: List[str]


@app.post("/cache/warm")
def warm_cache(request: CacheWarmRequest):
    """Pre-populate cache with frequently accessed guests."""
    db = SessionLocal()
    try:
        return warm_guest_cache(request.guest_ids, db)
    finally:
        db.close()


# -- Tracing Endpoints --

@app.get("/tracing/stats")
def tracing_statistics():
    """Get distributed tracing statistics."""
    return get_tracing_stats()


@app.get("/tracing/recent")
def recent_traces(limit: int = 50):
    """Get recent traces for debugging."""
    return {"traces": get_recent_traces(limit)}


@app.get("/tracing/trace/{trace_id}")
def get_trace(trace_id: str):
    """Get all spans for a specific trace ID."""
    spans = get_trace_by_id(trace_id)
    return {"trace_id": trace_id, "spans": spans}


@app.post("/tracing/clear")
def clear_traces():
    """Clear the trace buffer."""
    clear_trace_buffer()
    return {"message": "Trace buffer cleared"}


# -- Performance Budget Endpoints --

@app.get("/performance/stats")
def performance_statistics():
    """Get performance statistics and budget compliance."""
    return get_performance_stats()


@app.get("/performance/violations")
def performance_violations(limit: int = 50):
    """Get recent performance budget violations."""
    return {"violations": get_budget_violations(limit)}


@app.post("/performance/clear")
def clear_performance():
    """Clear all performance data."""
    clear_performance_data()
    return {"message": "Performance data cleared"}


# -- Secrets Management Endpoints --

@app.get("/secrets/status")
def secrets_status():
    """Get secrets management status (no actual secrets exposed)."""
    return get_secrets_status()


@app.get("/secrets/access-log")
def secrets_access_log(limit: int = 50):
    """Get secret access audit log."""
    return {"log": get_secret_access_log(limit)}


# ============================================================================
# PHASE 4: SYSTEM INFO & VERSION
# ============================================================================

@app.get("/system/info")
def system_info():
    """
    Get comprehensive system information.
    Single endpoint for operational dashboards.
    """
    import psutil
    
    return {
        "version": "2.0.0-phase4",
        "service": "resortOS-core",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "phase4_features": {
            "security": ["jwt", "rbac", "rate_limiting", "audit"],
            "resilience": ["circuit_breakers", "retry", "dlq", "degradation"],
            "observability": ["metrics", "tracing", "logging", "alerting"],
            "compliance": ["gdpr", "pdpa", "consent", "pii_handling"],
            "performance": ["caching", "budgets", "monitoring"],
            "disaster_recovery": ["backups", "restore"]
        },
        "resources": {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('/').percent
        },
        "endpoints_count": len(app.routes)
    }

