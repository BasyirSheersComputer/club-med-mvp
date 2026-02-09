"""
Secrets Management Service for Phase 4: Security
=================================================

Provides abstraction layer for secrets management:
- Environment-based secrets (development)
- GCP Secret Manager integration (production)
- Automatic rotation support
- Audit logging for secret access

Usage:
    from services.secrets import get_secret
    db_password = get_secret("DATABASE_PASSWORD")
"""
import os
import json
from datetime import datetime, timedelta
from typing import Any, Optional, Dict
from functools import lru_cache
from enum import Enum

# ============================================================================
# CONFIGURATION
# ============================================================================

class SecretSource(Enum):
    """Secret storage backends."""
    ENV = "environment"
    GCP = "gcp_secret_manager"
    VAULT = "hashicorp_vault"  # Future


# Determine secret source based on environment
SECRET_SOURCE = os.getenv("SECRET_SOURCE", "environment")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
SECRET_CACHE_TTL = int(os.getenv("SECRET_CACHE_TTL", "300"))  # 5 minutes

# In-memory cache for secrets
_secret_cache: Dict[str, Dict] = {}
_secret_access_log: list = []


# ============================================================================
# SECRET ACCESS LOGGING
# ============================================================================

def _log_secret_access(secret_name: str, source: str, success: bool):
    """Log secret access for audit compliance."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "secret_name": secret_name,
        "source": source,
        "success": success,
        "masked_value": True  # Never log actual values
    }
    _secret_access_log.append(entry)
    
    # Keep only last 1000 entries
    if len(_secret_access_log) > 1000:
        _secret_access_log.pop(0)


def get_secret_access_log(limit: int = 100) -> list:
    """Get recent secret access log entries."""
    return _secret_access_log[-limit:]


# ============================================================================
# ENVIRONMENT-BASED SECRETS (Development)
# ============================================================================

def _get_from_env(secret_name: str) -> Optional[str]:
    """Get secret from environment variable."""
    value = os.getenv(secret_name)
    _log_secret_access(secret_name, "ENV", value is not None)
    return value


# ============================================================================
# GCP SECRET MANAGER (Production)
# ============================================================================

_gcp_client = None

def _get_gcp_client():
    """Lazy-load GCP Secret Manager client."""
    global _gcp_client
    if _gcp_client is None:
        try:
            from google.cloud import secretmanager
            _gcp_client = secretmanager.SecretManagerServiceClient()
        except ImportError:
            print("⚠️ google-cloud-secret-manager not installed")
            return None
        except Exception as e:
            print(f"⚠️ GCP Secret Manager init failed: {e}")
            return None
    return _gcp_client


def _get_from_gcp(secret_name: str, version: str = "latest") -> Optional[str]:
    """Get secret from GCP Secret Manager."""
    client = _get_gcp_client()
    if not client or not GCP_PROJECT_ID:
        _log_secret_access(secret_name, "GCP", False)
        return None
    
    try:
        name = f"projects/{GCP_PROJECT_ID}/secrets/{secret_name}/versions/{version}"
        response = client.access_secret_version(request={"name": name})
        value = response.payload.data.decode("UTF-8")
        _log_secret_access(secret_name, "GCP", True)
        return value
    except Exception as e:
        print(f"⚠️ GCP Secret access failed for {secret_name}: {e}")
        _log_secret_access(secret_name, "GCP", False)
        return None


# ============================================================================
# MAIN SECRET ACCESS FUNCTION
# ============================================================================

def get_secret(
    secret_name: str,
    default: Optional[str] = None,
    use_cache: bool = True,
    required: bool = False
) -> Optional[str]:
    """
    Get a secret from the configured source.
    
    Args:
        secret_name: Name of the secret
        default: Default value if not found
        use_cache: Whether to use cached value
        required: Raise exception if not found
    
    Returns:
        Secret value or default
    """
    # Check cache first
    if use_cache and secret_name in _secret_cache:
        cached = _secret_cache[secret_name]
        if datetime.utcnow() < cached["expires"]:
            return cached["value"]
    
    # Get from appropriate source
    value = None
    
    if SECRET_SOURCE == "gcp_secret_manager":
        # Try GCP first, fall back to env
        value = _get_from_gcp(secret_name)
        if value is None:
            value = _get_from_env(secret_name)
    else:
        # Default: environment variables
        value = _get_from_env(secret_name)
    
    # Cache the result
    if value is not None and use_cache:
        _secret_cache[secret_name] = {
            "value": value,
            "expires": datetime.utcnow() + timedelta(seconds=SECRET_CACHE_TTL)
        }
    
    # Handle not found
    if value is None:
        if required:
            raise ValueError(f"Required secret '{secret_name}' not found")
        return default
    
    return value


def invalidate_secret_cache(secret_name: str = None):
    """
    Invalidate cached secret(s).
    
    Args:
        secret_name: Specific secret to invalidate, or None for all
    """
    global _secret_cache
    if secret_name:
        _secret_cache.pop(secret_name, None)
    else:
        _secret_cache.clear()


# ============================================================================
# COMMON SECRETS HELPERS
# ============================================================================

def get_database_url() -> str:
    """Get database connection URL."""
    return get_secret("DATABASE_URL", default="postgresql://postgres:postgres@db:5432/resortdb")


def get_redis_url() -> str:
    """Get Redis connection URL."""
    return get_secret("REDIS_URL", default="redis://redis:6379")


def get_jwt_secret() -> str:
    """Get JWT signing secret."""
    secret = get_secret("JWT_SECRET_KEY")
    if not secret:
        # Generate a default for development (NOT for production!)
        import secrets
        secret = secrets.token_hex(32)
        print("⚠️ Using generated JWT secret - set JWT_SECRET_KEY in production!")
    return secret


def get_openai_api_key() -> Optional[str]:
    """Get OpenAI API key."""
    return get_secret("OPENAI_API_KEY")


def get_gemini_api_key() -> Optional[str]:
    """Get Google Gemini API key."""
    return get_secret("GEMINI_API_KEY") or get_secret("GOOGLE_API_KEY")


# ============================================================================
# SECRET ROTATION SUPPORT
# ============================================================================

def rotate_secret(secret_name: str, new_value: str) -> Dict[str, Any]:
    """
    Rotate a secret (GCP Secret Manager only).
    
    Creates a new version of the secret.
    """
    if SECRET_SOURCE != "gcp_secret_manager":
        return {"error": "Secret rotation only supported with GCP Secret Manager"}
    
    client = _get_gcp_client()
    if not client or not GCP_PROJECT_ID:
        return {"error": "GCP Secret Manager not configured"}
    
    try:
        parent = f"projects/{GCP_PROJECT_ID}/secrets/{secret_name}"
        
        # Add new version
        response = client.add_secret_version(
            request={
                "parent": parent,
                "payload": {"data": new_value.encode("UTF-8")}
            }
        )
        
        # Invalidate cache
        invalidate_secret_cache(secret_name)
        
        return {
            "success": True,
            "secret_name": secret_name,
            "new_version": response.name.split("/")[-1]
        }
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# SECRETS STATUS
# ============================================================================

def get_secrets_status() -> Dict[str, Any]:
    """Get secrets management status and health."""
    return {
        "source": SECRET_SOURCE,
        "gcp_project": GCP_PROJECT_ID or "(not configured)",
        "cache_ttl_seconds": SECRET_CACHE_TTL,
        "cached_secrets_count": len(_secret_cache),
        "access_log_entries": len(_secret_access_log),
        "required_secrets": {
            "DATABASE_URL": get_secret("DATABASE_URL") is not None,
            "REDIS_URL": get_secret("REDIS_URL") is not None,
            "JWT_SECRET_KEY": get_secret("JWT_SECRET_KEY") is not None,
            "OPENAI_API_KEY": get_secret("OPENAI_API_KEY") is not None,
            "GEMINI_API_KEY": get_secret("GEMINI_API_KEY") is not None
        }
    }
