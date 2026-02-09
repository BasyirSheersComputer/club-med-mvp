"""
Compliance Service for Phase 4: GDPR/PDPA Handling
====================================================

Handles:
- Data Subject Access Requests (DSAR)
- Right to be Forgotten (data deletion)
- Data Portability (export)
- Anonymization
- PII Detection
- Consent Management
- Data Retention Policies
"""
import os
import re
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from enum import Enum

# ============================================================================
# CONFIGURATION
# ============================================================================

# Regional compliance requirements
COMPLIANCE_REGIONS = {
    "EU": {
        "name": "GDPR",
        "deletion_deadline_days": 30,
        "data_portability": True,
        "explicit_consent_required": True,
        "default_retention_days": 730  # 2 years
    },
    "SG": {
        "name": "PDPA",
        "deletion_deadline_days": 30,
        "data_portability": True,
        "explicit_consent_required": True,
        "default_retention_days": 365  # 1 year
    },
    "TH": {
        "name": "PDPA (Thailand)",
        "deletion_deadline_days": 30,
        "data_portability": True,
        "explicit_consent_required": True,
        "default_retention_days": 365
    },
    "DEFAULT": {
        "name": "Standard",
        "deletion_deadline_days": 90,
        "data_portability": False,
        "explicit_consent_required": False,
        "default_retention_days": 1095  # 3 years
    }
}

# PII detection patterns
PII_PATTERNS = {
    "email": r'[\w.+-]+@[\w-]+\.[\w.-]+',
    "phone": r'\+?\d{10,15}',
    "credit_card": r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
    "passport": r'\b[A-Z]{1,2}\d{6,9}\b',
    "ip_address": r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b',
    "address": r'\d+\s+[\w\s]+(?:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr)',
    "date_of_birth": r'\b(?:0?[1-9]|[12][0-9]|3[01])[\/\-](?:0?[1-9]|1[012])[\/\-](?:19|20)\d{2}\b',
}


class RequestType(Enum):
    """Types of data subject requests."""
    DELETION = "deletion"  # Right to be forgotten
    EXPORT = "export"      # Data portability
    ACCESS = "access"      # DSAR
    RECTIFICATION = "rectification"  # Right to correct
    ANONYMIZATION = "anonymization"


class ConsentType(Enum):
    """Types of consent that can be granted/withdrawn."""
    MARKETING = "marketing"
    ANALYTICS = "analytics"
    NECESSARY = "necessary"  # Cannot be withdrawn
    PROFILING = "profiling"


# ============================================================================
# PII DETECTION
# ============================================================================

def detect_pii(text: str) -> Dict[str, Any]:
    """
    Detect PII in text content.
    
    Returns:
        {
            "contains_pii": bool,
            "categories": ["email", "phone", ...],
            "matches": {"email": ["found@email.com"], ...}
        }
    """
    if not text:
        return {"contains_pii": False, "categories": [], "matches": {}}
    
    categories = []
    matches = {}
    
    for category, pattern in PII_PATTERNS.items():
        found = re.findall(pattern, text, re.IGNORECASE)
        if found:
            categories.append(category)
            matches[category] = found
    
    return {
        "contains_pii": len(categories) > 0,
        "categories": categories,
        "matches": matches
    }


def mask_pii_in_text(text: str) -> str:
    """
    Mask all detected PII in text with placeholders.
    """
    if not text:
        return text
    
    masked = text
    
    for category, pattern in PII_PATTERNS.items():
        replacement = f"[{category.upper()}_REDACTED]"
        masked = re.sub(pattern, replacement, masked, flags=re.IGNORECASE)
    
    return masked


def anonymize_pii(text: str, salt: str = "") -> str:
    """
    Anonymize PII by replacing with hashed values.
    Preserves format but removes identifying information.
    """
    if not text:
        return text
    
    def hash_match(match, category: str) -> str:
        value = match.group(0)
        hashed = hashlib.sha256(f"{value}{salt}".encode()).hexdigest()[:8]
        return f"[ANON_{category.upper()}_{hashed}]"
    
    result = text
    for category, pattern in PII_PATTERNS.items():
        result = re.sub(
            pattern,
            lambda m, c=category: hash_match(m, c),
            result,
            flags=re.IGNORECASE
        )
    
    return result


# ============================================================================
# DATA EXPORT (GDPR Article 20 - Data Portability)
# ============================================================================

def export_guest_data(guest_id: str, db) -> Dict[str, Any]:
    """
    Export all data for a guest in a portable format.
    GDPR Article 20 compliance.
    
    Returns machine-readable JSON with all guest data.
    """
    from models import GuestModel, MessageModel, ThreadModel
    
    guest = db.query(GuestModel).filter(GuestModel.id == guest_id).first()
    
    if not guest:
        return {"error": "Guest not found", "guest_id": guest_id}
    
    # Export guest profile
    export_data = {
        "export_timestamp": datetime.utcnow().isoformat() + "Z",
        "export_format": "GDPR_DSAR_v1.0",
        "data_subject": {
            "id": guest.id,
            "name": guest.name,
            "email": guest.email,
            "phone": guest.phone,
            "language": guest.language,
            "country_code": getattr(guest, 'country_code', None),
            "created_at": guest.created_at.isoformat() if guest.created_at else None,
        },
        "consent_records": {
            "marketing": getattr(guest, 'consent_marketing', False),
            "analytics": getattr(guest, 'consent_analytics', False),
            "consent_timestamp": getattr(guest, 'consent_timestamp', None)
        },
        "channel_identifiers": guest.channel_ids or {},
        "messages": [],
        "threads": []
    }
    
    # Export all messages
    messages = db.query(MessageModel).filter(MessageModel.guest_id == guest_id).all()
    for msg in messages:
        export_data["messages"].append({
            "id": msg.id,
            "channel": msg.channel,
            "direction": msg.direction,
            "content_type": msg.content_type,
            "body": msg.body,
            "timestamp": msg.timestamp.isoformat() if msg.timestamp else None
        })
    
    # Export thread metadata
    threads = db.query(ThreadModel).filter(ThreadModel.guest_id == guest_id).all()
    for thread in threads:
        export_data["threads"].append({
            "id": thread.id,
            "status": thread.status,
            "created_at": thread.created_at.isoformat() if thread.created_at else None,
            "message_count": len([m for m in messages if m.thread_id == thread.id])
        })
    
    # Update export timestamp on guest record
    guest.data_exported_at = datetime.utcnow()
    db.commit()
    
    print(f"📦 Data exported for guest {guest_id}: {len(messages)} messages, {len(threads)} threads")
    
    return export_data


# ============================================================================
# DATA DELETION (GDPR Article 17 - Right to be Forgotten)
# ============================================================================

def delete_guest_data(
    guest_id: str,
    db,
    hard_delete: bool = False,
    reason: str = None,
    requester_id: str = None
) -> Dict[str, Any]:
    """
    Delete or anonymize all guest data.
    
    Args:
        guest_id: Guest to delete
        hard_delete: If True, permanently delete. If False, anonymize.
        reason: Reason for deletion request
        requester_id: User ID processing the request
    
    Returns summary of deleted/anonymized data.
    """
    from models import GuestModel, MessageModel, ThreadModel, DataDeletionRequest
    
    guest = db.query(GuestModel).filter(GuestModel.id == guest_id).first()
    
    if not guest:
        return {"error": "Guest not found", "guest_id": guest_id}
    
    result = {
        "guest_id": guest_id,
        "action": "hard_delete" if hard_delete else "anonymize",
        "timestamp": datetime.utcnow().isoformat(),
        "messages_affected": 0,
        "threads_affected": 0
    }
    
    # Get related data counts
    messages = db.query(MessageModel).filter(MessageModel.guest_id == guest_id).all()
    threads = db.query(ThreadModel).filter(ThreadModel.guest_id == guest_id).all()
    
    result["messages_affected"] = len(messages)
    result["threads_affected"] = len(threads)
    
    if hard_delete:
        # Permanently delete all data
        for msg in messages:
            db.delete(msg)
        for thread in threads:
            db.delete(thread)
        db.delete(guest)
        db.commit()
        print(f"🗑️ Hard deleted guest {guest_id}")
    else:
        # Anonymize instead of delete
        anonymization_salt = str(datetime.utcnow().timestamp())
        
        # Anonymize guest profile
        guest.name = f"[DELETED_USER_{guest_id[:8]}]"
        guest.email = None
        guest.phone = None
        guest.channel_ids = {}
        guest.anonymized_at = datetime.utcnow()
        
        # Anonymize messages
        for msg in messages:
            if msg.body:
                msg.body = anonymize_pii(msg.body, anonymization_salt)
            msg.sender_id = f"anon_{guest_id[:8]}"
        
        db.commit()
        print(f"🔒 Anonymized guest {guest_id}")
    
    # Create deletion record for audit trail
    try:
        deletion_record = DataDeletionRequest(
            guest_id=guest_id if not hard_delete else "[DELETED]",
            request_type="deletion" if hard_delete else "anonymization",
            reason=reason,
            status="completed",
            processed_at=datetime.utcnow(),
            processed_by=requester_id
        )
        db.add(deletion_record)
        db.commit()
    except Exception as e:
        print(f"⚠️ Could not create deletion record: {e}")
    
    return result


# ============================================================================
# CONSENT MANAGEMENT
# ============================================================================

def update_consent(
    guest_id: str,
    consent_type: str,
    granted: bool,
    db,
    source: str = "api",
    ip_address: str = None
) -> Dict[str, Any]:
    """
    Update consent status for a guest.
    Creates audit log entry for GDPR Article 7 compliance.
    """
    from models import GuestModel, ConsentLog
    
    guest = db.query(GuestModel).filter(GuestModel.id == guest_id).first()
    
    if not guest:
        return {"error": "Guest not found"}
    
    # Get previous value
    consent_field = f"consent_{consent_type}"
    previous_value = getattr(guest, consent_field, None) if hasattr(guest, consent_field) else None
    
    # Update guest consent
    if consent_type == "marketing":
        guest.consent_marketing = granted
    elif consent_type == "analytics":
        guest.consent_analytics = granted
    
    guest.consent_timestamp = datetime.utcnow()
    
    # Create audit log
    log_entry = ConsentLog(
        guest_id=guest_id,
        consent_type=consent_type,
        action="granted" if granted else "withdrawn",
        previous_value=previous_value,
        new_value=granted,
        source=source,
        ip_address=ip_address
    )
    db.add(log_entry)
    db.commit()
    
    print(f"🔐 Consent updated for guest {guest_id}: {consent_type} = {granted}")
    
    return {
        "guest_id": guest_id,
        "consent_type": consent_type,
        "granted": granted,
        "previous_value": previous_value,
        "timestamp": datetime.utcnow().isoformat()
    }


def get_consent_history(guest_id: str, db) -> List[Dict]:
    """Get consent change history for a guest."""
    from models import ConsentLog
    
    logs = db.query(ConsentLog).filter(
        ConsentLog.guest_id == guest_id
    ).order_by(ConsentLog.created_at.desc()).all()
    
    return [
        {
            "consent_type": log.consent_type,
            "action": log.action,
            "previous_value": log.previous_value,
            "new_value": log.new_value,
            "source": log.source,
            "timestamp": log.created_at.isoformat()
        }
        for log in logs
    ]


# ============================================================================
# DATA RETENTION
# ============================================================================

def apply_retention_policy(db, dry_run: bool = True) -> Dict[str, Any]:
    """
    Apply data retention policies based on guest country/settings.
    
    Args:
        dry_run: If True, only report what would be deleted
    
    Returns summary of affected records.
    """
    from models import GuestModel, MessageModel
    
    now = datetime.utcnow()
    results = {
        "timestamp": now.isoformat(),
        "dry_run": dry_run,
        "guests_affected": 0,
        "messages_affected": 0,
        "by_region": {}
    }
    
    # Find guests with expired retention
    guests = db.query(GuestModel).all()
    
    for guest in guests:
        retention_days = getattr(guest, 'data_retention_days', 730)
        if not guest.created_at:
            continue
        
        expiry_date = guest.created_at + timedelta(days=retention_days)
        
        if now > expiry_date:
            country = getattr(guest, 'country_code', 'DEFAULT') or 'DEFAULT'
            
            if country not in results["by_region"]:
                results["by_region"][country] = {"guests": 0, "messages": 0}
            
            results["by_region"][country]["guests"] += 1
            results["guests_affected"] += 1
            
            # Count messages
            msg_count = db.query(MessageModel).filter(
                MessageModel.guest_id == guest.id
            ).count()
            results["by_region"][country]["messages"] += msg_count
            results["messages_affected"] += msg_count
            
            if not dry_run:
                # Actually anonymize expired data
                delete_guest_data(guest.id, db, hard_delete=False, reason="retention_policy")
    
    return results


# ============================================================================
# COMPLIANCE STATUS
# ============================================================================

def get_compliance_status(db) -> Dict[str, Any]:
    """
    Get overall compliance status and metrics.
    """
    from models import GuestModel, DataDeletionRequest, ConsentLog
    
    now = datetime.utcnow()
    
    # Count guests by consent status
    total_guests = db.query(GuestModel).count()
    
    # Get pending deletion requests
    pending_deletions = db.query(DataDeletionRequest).filter(
        DataDeletionRequest.status == "pending"
    ).count()
    
    # Overdue deletion requests (past deadline)
    overdue = 0
    pending_requests = db.query(DataDeletionRequest).filter(
        DataDeletionRequest.status == "pending"
    ).all()
    for req in pending_requests:
        if req.deadline and req.deadline < now:
            overdue += 1
    
    # Recent consent changes (last 30 days)
    thirty_days_ago = now - timedelta(days=30)
    recent_consent_changes = db.query(ConsentLog).filter(
        ConsentLog.created_at >= thirty_days_ago
    ).count()
    
    return {
        "timestamp": now.isoformat(),
        "total_guests": total_guests,
        "requests": {
            "pending": pending_deletions,
            "overdue": overdue
        },
        "consent": {
            "recent_changes_30d": recent_consent_changes
        },
        "compliance_status": "at_risk" if overdue > 0 else "compliant"
    }
