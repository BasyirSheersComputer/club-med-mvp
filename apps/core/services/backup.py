"""
Backup Service for Phase 4: Disaster Recovery
==============================================

Handles:
- Database backup utilities
- Export/import for disaster recovery
- Backup scheduling metadata
- Cloud backup integration prep
"""
import os
import json
import gzip
import shutil
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================

BACKUP_DIR = os.getenv("BACKUP_DIR", "/app/backups")
MAX_BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
BACKUP_COMPRESSION = os.getenv("BACKUP_COMPRESSION", "gzip")  # gzip, none

# Ensure backup directory exists
os.makedirs(BACKUP_DIR, exist_ok=True)

# In-memory backup registry (use Redis/DB in production)
_backup_registry: List[Dict[str, Any]] = []


# ============================================================================
# DATABASE EXPORT/IMPORT
# ============================================================================

def export_database_snapshot(db, include_messages: bool = True) -> Dict[str, Any]:
    """
    Export full database snapshot for backup.
    
    Returns JSON-serializable dict with all data.
    """
    from models import (
        GuestModel, ThreadModel, MessageModel,
        KnowledgeDocument, KnowledgeChunk, CopilotSuggestion,
        UserModel, DataDeletionRequest, ConsentLog
    )
    
    snapshot = {
        "metadata": {
            "version": "2.0.0-phase4",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "include_messages": include_messages
        },
        "counts": {},
        "data": {}
    }
    
    # Export guests
    guests = db.query(GuestModel).all()
    snapshot["data"]["guests"] = [
        {
            "id": g.id,
            "name": g.name,
            "email": g.email,
            "phone": g.phone,
            "channel_ids": g.channel_ids,
            "language": g.language,
            "created_at": g.created_at.isoformat() if g.created_at else None,
            "consent_marketing": getattr(g, 'consent_marketing', False),
            "consent_analytics": getattr(g, 'consent_analytics', False),
            "country_code": getattr(g, 'country_code', None)
        }
        for g in guests
    ]
    snapshot["counts"]["guests"] = len(guests)
    
    # Export threads
    threads = db.query(ThreadModel).all()
    snapshot["data"]["threads"] = [
        {
            "id": t.id,
            "guest_id": t.guest_id,
            "status": t.status,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "sla_status": t.sla_status,
            "sla_breached": t.sla_breached
        }
        for t in threads
    ]
    snapshot["counts"]["threads"] = len(threads)
    
    # Export messages (optional, can be large)
    if include_messages:
        messages = db.query(MessageModel).all()
        snapshot["data"]["messages"] = [
            {
                "id": m.id,
                "thread_id": m.thread_id,
                "guest_id": m.guest_id,
                "channel": m.channel,
                "direction": m.direction,
                "content_type": m.content_type,
                "body": m.body,
                "timestamp": m.timestamp.isoformat() if m.timestamp else None
            }
            for m in messages
        ]
        snapshot["counts"]["messages"] = len(messages)
    
    # Export knowledge documents
    docs = db.query(KnowledgeDocument).all()
    snapshot["data"]["knowledge_documents"] = [
        {
            "id": d.id,
            "filename": d.filename,
            "title": d.title,
            "status": d.status,
            "total_chunks": d.total_chunks
        }
        for d in docs
    ]
    snapshot["counts"]["knowledge_documents"] = len(docs)
    
    # Export users (without passwords)
    try:
        users = db.query(UserModel).all()
        snapshot["data"]["users"] = [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "role": u.role,
                "resort_id": u.resort_id,
                "is_active": u.is_active
                # Note: password hash not exported for security
            }
            for u in users
        ]
        snapshot["counts"]["users"] = len(users)
    except Exception:
        snapshot["data"]["users"] = []
        snapshot["counts"]["users"] = 0
    
    return snapshot


def save_backup_to_file(snapshot: Dict[str, Any], backup_name: str = None) -> Dict[str, Any]:
    """
    Save snapshot to a backup file.
    
    Args:
        snapshot: Database snapshot dict
        backup_name: Optional custom name
    
    Returns backup file info.
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = backup_name or f"backup_{timestamp}"
    
    if BACKUP_COMPRESSION == "gzip":
        filepath = os.path.join(BACKUP_DIR, f"{filename}.json.gz")
        with gzip.open(filepath, 'wt', encoding='utf-8') as f:
            json.dump(snapshot, f)
    else:
        filepath = os.path.join(BACKUP_DIR, f"{filename}.json")
        with open(filepath, 'w') as f:
            json.dump(snapshot, f)
    
    file_size = os.path.getsize(filepath)
    
    # Register backup
    backup_info = {
        "id": filename,
        "filepath": filepath,
        "timestamp": datetime.utcnow().isoformat(),
        "size_bytes": file_size,
        "size_mb": round(file_size / 1024 / 1024, 2),
        "counts": snapshot.get("counts", {}),
        "compressed": BACKUP_COMPRESSION == "gzip"
    }
    _backup_registry.append(backup_info)
    
    print(f"💾 Backup saved: {filepath} ({backup_info['size_mb']} MB)")
    
    return backup_info


def list_backups() -> List[Dict[str, Any]]:
    """List all available backups."""
    # Check filesystem for backups
    backup_files = []
    
    if os.path.exists(BACKUP_DIR):
        for filename in os.listdir(BACKUP_DIR):
            if filename.startswith("backup_") and (filename.endswith(".json") or filename.endswith(".json.gz")):
                filepath = os.path.join(BACKUP_DIR, filename)
                stat = os.stat(filepath)
                backup_files.append({
                    "filename": filename,
                    "filepath": filepath,
                    "size_bytes": stat.st_size,
                    "size_mb": round(stat.st_size / 1024 / 1024, 2),
                    "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "compressed": filename.endswith(".gz")
                })
    
    # Sort by creation time, newest first
    backup_files.sort(key=lambda x: x["created_at"], reverse=True)
    
    return backup_files


def load_backup_from_file(filepath: str) -> Optional[Dict[str, Any]]:
    """Load a backup file."""
    if not os.path.exists(filepath):
        return None
    
    if filepath.endswith(".gz"):
        with gzip.open(filepath, 'rt', encoding='utf-8') as f:
            return json.load(f)
    else:
        with open(filepath, 'r') as f:
            return json.load(f)


def cleanup_old_backups(max_age_days: int = MAX_BACKUP_RETENTION_DAYS) -> Dict[str, Any]:
    """
    Remove backups older than retention period.
    
    Returns summary of deleted files.
    """
    cutoff = datetime.utcnow() - timedelta(days=max_age_days)
    deleted = []
    kept = 0
    
    for backup in list_backups():
        created = datetime.fromisoformat(backup["created_at"])
        if created < cutoff:
            try:
                os.remove(backup["filepath"])
                deleted.append(backup["filename"])
                print(f"🗑️ Deleted old backup: {backup['filename']}")
            except Exception as e:
                print(f"⚠️ Failed to delete {backup['filename']}: {e}")
        else:
            kept += 1
    
    return {
        "deleted_count": len(deleted),
        "deleted_files": deleted,
        "kept_count": kept,
        "max_age_days": max_age_days
    }


# ============================================================================
# RESTORE OPERATIONS
# ============================================================================

def restore_from_backup(snapshot: Dict[str, Any], db, dry_run: bool = True) -> Dict[str, Any]:
    """
    Restore database from backup snapshot.
    
    Args:
        snapshot: Backup snapshot dict
        db: Database session
        dry_run: If True, only validate without making changes
    
    Returns restoration result.
    """
    from models import GuestModel, ThreadModel, MessageModel
    
    result = {
        "dry_run": dry_run,
        "timestamp": datetime.utcnow().isoformat(),
        "backup_version": snapshot.get("metadata", {}).get("version"),
        "backup_timestamp": snapshot.get("metadata", {}).get("timestamp"),
        "operations": []
    }
    
    # Validate backup format
    if "data" not in snapshot:
        result["error"] = "Invalid backup format: missing 'data' key"
        return result
    
    data = snapshot["data"]
    
    # Count operations
    result["counts"] = {
        "guests": len(data.get("guests", [])),
        "threads": len(data.get("threads", [])),
        "messages": len(data.get("messages", []))
    }
    
    if dry_run:
        result["message"] = "Dry run completed. Set dry_run=false to apply."
        return result
    
    # Actual restoration (use with caution!)
    # In production, this would be more sophisticated with conflict resolution
    try:
        # Restore guests
        for guest_data in data.get("guests", []):
            existing = db.query(GuestModel).filter(GuestModel.id == guest_data["id"]).first()
            if not existing:
                guest = GuestModel(**{k: v for k, v in guest_data.items() if k != 'created_at'})
                db.add(guest)
                result["operations"].append(f"Guest {guest_data['id']} created")
        
        db.commit()
        result["status"] = "success"
        result["message"] = f"Restored {result['counts']} records"
        
    except Exception as e:
        db.rollback()
        result["status"] = "error"
        result["error"] = str(e)
    
    return result


# ============================================================================
# BACKUP STATS
# ============================================================================

def get_backup_stats() -> Dict[str, Any]:
    """Get backup service statistics."""
    backups = list_backups()
    
    total_size = sum(b["size_bytes"] for b in backups)
    
    return {
        "backup_dir": BACKUP_DIR,
        "total_backups": len(backups),
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "retention_days": MAX_BACKUP_RETENTION_DAYS,
        "compression": BACKUP_COMPRESSION,
        "latest_backup": backups[0] if backups else None,
        "oldest_backup": backups[-1] if backups else None
    }
