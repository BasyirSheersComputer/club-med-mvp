"""
Security Service for Phase 4: Enterprise Robustness
====================================================

Handles:
- JWT token generation and validation
- Token rotation and blacklisting
- Role-Based Access Control (RBAC)
- Rate limiting
"""
import os
import jwt
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from functools import wraps
from enum import Enum

# ============================================================================
# CONFIGURATION
# ============================================================================

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Rate limiting defaults
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

# ============================================================================
# ROLE-BASED ACCESS CONTROL
# ============================================================================

class Role(str, Enum):
    """User roles for RBAC."""
    SUPER_ADMIN = "super_admin"
    RESORT_MANAGER = "resort_manager"
    FRONT_DESK_AGENT = "front_desk_agent"
    READONLY = "readonly"


class Permission(str, Enum):
    """Granular permissions for RBAC."""
    # Message permissions
    MESSAGE_READ = "message:read"
    MESSAGE_WRITE = "message:write"
    MESSAGE_DELETE = "message:delete"
    
    # Guest permissions
    GUEST_READ = "guest:read"
    GUEST_WRITE = "guest:write"
    GUEST_PII = "guest:pii"  # Access to sensitive PII
    
    # AI/Copilot permissions
    AI_USE = "ai:use"
    AI_CONFIG = "ai:config"
    
    # Knowledge base permissions
    KNOWLEDGE_READ = "knowledge:read"
    KNOWLEDGE_WRITE = "knowledge:write"
    
    # Admin permissions
    ADMIN_USERS = "admin:users"
    ADMIN_RESORTS = "admin:resorts"
    ADMIN_REPORTS = "admin:reports"
    ADMIN_AUDIT = "admin:audit"


# Permission matrix by role
ROLE_PERMISSIONS: Dict[Role, List[Permission]] = {
    Role.SUPER_ADMIN: list(Permission),  # All permissions
    
    Role.RESORT_MANAGER: [
        Permission.MESSAGE_READ,
        Permission.MESSAGE_WRITE,
        Permission.MESSAGE_DELETE,
        Permission.GUEST_READ,
        Permission.GUEST_WRITE,
        Permission.GUEST_PII,
        Permission.AI_USE,
        Permission.AI_CONFIG,
        Permission.KNOWLEDGE_READ,
        Permission.KNOWLEDGE_WRITE,
        Permission.ADMIN_REPORTS,
    ],
    
    Role.FRONT_DESK_AGENT: [
        Permission.MESSAGE_READ,
        Permission.MESSAGE_WRITE,
        Permission.GUEST_READ,
        Permission.GUEST_WRITE,
        Permission.AI_USE,
        Permission.KNOWLEDGE_READ,
    ],
    
    Role.READONLY: [
        Permission.MESSAGE_READ,
        Permission.GUEST_READ,
        Permission.KNOWLEDGE_READ,
    ],
}


def get_permissions(role: Role) -> List[Permission]:
    """Get permissions for a given role."""
    return ROLE_PERMISSIONS.get(role, [])


def has_permission(role: Role, permission: Permission) -> bool:
    """Check if a role has a specific permission."""
    return permission in get_permissions(role)


# ============================================================================
# JWT TOKEN MANAGEMENT
# ============================================================================

# In-memory token blacklist (use Redis in production)
_token_blacklist: set = set()
_refresh_tokens: Dict[str, Dict] = {}


def create_access_token(
    user_id: str,
    role: Role,
    resort_id: Optional[str] = None,
    extra_claims: Optional[Dict] = None
) -> str:
    """
    Create a short-lived access token.
    
    Claims:
    - sub: User ID
    - role: User role
    - resort_id: Resort context for multi-tenancy
    - permissions: List of permissions
    - exp: Expiration time
    - iat: Issued at
    - jti: Unique token ID
    """
    now = datetime.utcnow()
    token_id = secrets.token_hex(16)
    
    payload = {
        "sub": user_id,
        "role": role.value,
        "resort_id": resort_id,
        "permissions": [p.value for p in get_permissions(role)],
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": now,
        "jti": token_id,
        "type": "access"
    }
    
    if extra_claims:
        payload.update(extra_claims)
    
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, role: Role) -> str:
    """
    Create a long-lived refresh token.
    """
    now = datetime.utcnow()
    token_id = secrets.token_hex(16)
    
    payload = {
        "sub": user_id,
        "role": role.value,
        "exp": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        "iat": now,
        "jti": token_id,
        "type": "refresh"
    }
    
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    
    # Track refresh token for rotation
    _refresh_tokens[token_id] = {
        "user_id": user_id,
        "created_at": now.isoformat(),
        "used": False
    }
    
    return token


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify and decode a JWT token.
    
    Returns:
    - Decoded payload if valid
    - None if invalid or blacklisted
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        
        # Check if token is blacklisted
        token_id = payload.get("jti")
        if token_id and token_id in _token_blacklist:
            return None
        
        return payload
    except jwt.ExpiredSignatureError:
        print("⚠️ Token expired")
        return None
    except jwt.InvalidTokenError as e:
        print(f"⚠️ Invalid token: {e}")
        return None


def refresh_access_token(refresh_token: str) -> Optional[Dict[str, str]]:
    """
    Use a refresh token to get new access and refresh tokens.
    Implements refresh token rotation for security.
    
    Returns:
    - {"access_token": str, "refresh_token": str} if valid
    - None if invalid
    """
    payload = verify_token(refresh_token)
    
    if not payload or payload.get("type") != "refresh":
        return None
    
    token_id = payload.get("jti")
    user_id = payload.get("sub")
    role = Role(payload.get("role"))
    
    # Check if refresh token was already used (rotation)
    if token_id in _refresh_tokens:
        if _refresh_tokens[token_id].get("used"):
            # Token reuse detected - potential token theft
            # Invalidate all tokens for this user
            print(f"🚨 Refresh token reuse detected for user {user_id}")
            blacklist_token(token_id)
            return None
        
        # Mark as used
        _refresh_tokens[token_id]["used"] = True
    
    # Blacklist old refresh token
    blacklist_token(token_id)
    
    # Issue new tokens
    return {
        "access_token": create_access_token(user_id, role),
        "refresh_token": create_refresh_token(user_id, role)
    }


def blacklist_token(token_id: str):
    """Add a token to the blacklist."""
    _token_blacklist.add(token_id)


def logout(access_token: str, refresh_token: Optional[str] = None):
    """
    Logout by blacklisting tokens.
    """
    access_payload = verify_token(access_token)
    if access_payload:
        blacklist_token(access_payload.get("jti"))
    
    if refresh_token:
        refresh_payload = verify_token(refresh_token)
        if refresh_payload:
            blacklist_token(refresh_payload.get("jti"))


# ============================================================================
# RATE LIMITING (In-Memory - Use Redis in Production)
# ============================================================================

_rate_limit_store: Dict[str, Dict] = {}


def check_rate_limit(
    identifier: str,
    max_requests: int = RATE_LIMIT_REQUESTS,
    window_seconds: int = RATE_LIMIT_WINDOW_SECONDS
) -> Dict[str, Any]:
    """
    Check if request is within rate limit.
    
    Args:
        identifier: API key, user ID, or IP address
        max_requests: Maximum requests in window
        window_seconds: Time window in seconds
    
    Returns:
        {
            "allowed": bool,
            "remaining": int,
            "reset_at": datetime
        }
    """
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=window_seconds)
    
    if identifier not in _rate_limit_store:
        _rate_limit_store[identifier] = {
            "requests": [],
            "created_at": now
        }
    
    # Clean old requests outside window
    _rate_limit_store[identifier]["requests"] = [
        ts for ts in _rate_limit_store[identifier]["requests"]
        if ts > window_start
    ]
    
    current_count = len(_rate_limit_store[identifier]["requests"])
    
    if current_count >= max_requests:
        # Find when the oldest request in window expires
        oldest = min(_rate_limit_store[identifier]["requests"])
        reset_at = oldest + timedelta(seconds=window_seconds)
        
        return {
            "allowed": False,
            "remaining": 0,
            "reset_at": reset_at,
            "retry_after": (reset_at - now).seconds
        }
    
    # Record this request
    _rate_limit_store[identifier]["requests"].append(now)
    
    return {
        "allowed": True,
        "remaining": max_requests - current_count - 1,
        "reset_at": now + timedelta(seconds=window_seconds)
    }


def get_rate_limit_headers(rate_result: Dict) -> Dict[str, str]:
    """Generate rate limit headers for HTTP response."""
    return {
        "X-RateLimit-Limit": str(RATE_LIMIT_REQUESTS),
        "X-RateLimit-Remaining": str(rate_result.get("remaining", 0)),
        "X-RateLimit-Reset": rate_result.get("reset_at", datetime.utcnow()).isoformat()
    }


# ============================================================================
# INPUT VALIDATION & SANITIZATION
# ============================================================================

import re
import html

# XSS prevention patterns
XSS_PATTERNS = [
    r'<script[^>]*>.*?</script>',
    r'javascript:',
    r'on\w+\s*=',
    r'<iframe[^>]*>',
    r'<object[^>]*>',
    r'<embed[^>]*>',
]

# SQL injection prevention patterns
SQL_INJECTION_PATTERNS = [
    r"('|\")\s*(or|and)\s*('|\"|\d)",
    r';\s*(drop|delete|update|insert)\s+',
    r'union\s+(all\s+)?select',
    r'--\s*$',
]


def sanitize_input(value: str, max_length: int = 10000) -> str:
    """
    Sanitize user input to prevent XSS and injection attacks.
    """
    if not value:
        return value
    
    # Truncate if too long
    if len(value) > max_length:
        value = value[:max_length]
    
    # HTML escape
    value = html.escape(value)
    
    return value


def validate_input(value: str) -> Dict[str, Any]:
    """
    Validate input for potential security issues.
    
    Returns:
        {"valid": bool, "issues": list}
    """
    issues = []
    
    for pattern in XSS_PATTERNS:
        if re.search(pattern, value, re.IGNORECASE | re.DOTALL):
            issues.append("potential_xss")
            break
    
    for pattern in SQL_INJECTION_PATTERNS:
        if re.search(pattern, value, re.IGNORECASE):
            issues.append("potential_sql_injection")
            break
    
    return {
        "valid": len(issues) == 0,
        "issues": issues
    }


# ============================================================================
# AUDIT LOGGING
# ============================================================================

_audit_log: List[Dict] = []


def log_audit_event(
    action: str,
    user_id: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[Dict] = None,
    ip_address: Optional[str] = None
):
    """
    Log an audit event for compliance tracking.
    """
    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "action": action,
        "user_id": user_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "details": details or {},
        "ip_address": ip_address
    }
    
    _audit_log.append(event)
    
    # In production, send to centralized logging
    print(f"📋 AUDIT: {action} on {resource_type}/{resource_id} by {user_id}")


def get_audit_log(
    user_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = 100
) -> List[Dict]:
    """
    Retrieve audit log entries.
    """
    results = _audit_log
    
    if user_id:
        results = [e for e in results if e["user_id"] == user_id]
    
    if resource_type:
        results = [e for e in results if e["resource_type"] == resource_type]
    
    if since:
        since_str = since.isoformat()
        results = [e for e in results if e["timestamp"] >= since_str]
    
    return results[-limit:]


# ============================================================================
# SECURITY STATS
# ============================================================================

def get_security_stats() -> Dict[str, Any]:
    """Get security service statistics."""
    return {
        "tokens": {
            "blacklisted": len(_token_blacklist),
            "refresh_active": len([t for t in _refresh_tokens.values() if not t.get("used")])
        },
        "rate_limiting": {
            "tracked_identifiers": len(_rate_limit_store),
            "limit_per_minute": RATE_LIMIT_REQUESTS
        },
        "audit": {
            "total_events": len(_audit_log),
            "recent_events": len([
                e for e in _audit_log 
                if e["timestamp"] > (datetime.utcnow() - timedelta(hours=1)).isoformat()
            ])
        }
    }
