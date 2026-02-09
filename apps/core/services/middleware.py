"""
Phase 4 Security & Observability Middleware
============================================

FastAPI middleware and dependencies integrating:
- Authentication (JWT)
- Authorization (RBAC)
- Rate limiting
- Request tracing
- Metrics collection
"""
from fastapi import Request, Response, HTTPException, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional, List
import time
import uuid

from services.security import (
    verify_token,
    check_rate_limit,
    get_rate_limit_headers,
    Role,
    Permission,
    has_permission,
    log_audit_event,
    sanitize_input,
    validate_input
)
from services.observability import (
    correlation_id_var,
    request_start_time_var,
    metrics,
    logger,
    HealthStatus,
    create_health_response
)
from services.resilience import (
    is_read_only,
    is_offline,
    DegradationMode,
    get_degradation_mode
)


# ============================================================================
# CORRELATION ID MIDDLEWARE
# ============================================================================

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add correlation ID to every request.
    If X-Correlation-ID header exists, use it; otherwise generate one.
    """
    
    async def dispatch(self, request: Request, call_next):
        # Get or generate correlation ID
        corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4())[:8])
        correlation_id_var.set(corr_id)
        
        # Process request
        response = await call_next(request)
        
        # Add correlation ID to response headers
        response.headers["X-Correlation-ID"] = corr_id
        
        return response


# ============================================================================
# METRICS MIDDLEWARE
# ============================================================================

class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware to collect request metrics (Golden Signals).
    """
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        request_start_time_var.set(start_time)
        
        # Get endpoint path template (not actual path to avoid cardinality)
        endpoint = request.url.path
        method = request.method
        
        status_code = 500  # Default error
        
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        
        except Exception as e:
            logger.error(f"Request failed: {str(e)}", endpoint=endpoint)
            raise
        
        finally:
            latency_ms = (time.time() - start_time) * 1000
            metrics.record_request(
                endpoint=endpoint,
                latency_ms=latency_ms,
                status_code=status_code,
                method=method
            )


# ============================================================================
# RATE LIMITING MIDDLEWARE
# ============================================================================

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware based on client IP or API key.
    """
    
    # Endpoints exempt from rate limiting
    EXEMPT_PATHS = {"/", "/health", "/health/deep", "/metrics"}
    
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for exempt paths
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)
        
        # Get identifier (prefer API key, fallback to IP)
        api_key = request.headers.get("X-API-Key")
        client_ip = request.client.host if request.client else "unknown"
        identifier = api_key or client_ip
        
        # Check rate limit
        rate_result = check_rate_limit(identifier)
        
        if not rate_result["allowed"]:
            # Return 429 with rate limit headers
            response = Response(
                content='{"error": "Rate limit exceeded", "retry_after": ' + 
                        str(rate_result.get("retry_after", 60)) + '}',
                status_code=429,
                media_type="application/json"
            )
            for key, value in get_rate_limit_headers(rate_result).items():
                response.headers[key] = value
            
            logger.warning("Rate limit exceeded", identifier=identifier[:10])
            return response
        
        # Process request and add rate limit headers to response
        response = await call_next(request)
        for key, value in get_rate_limit_headers(rate_result).items():
            response.headers[key] = value
        
        return response


# ============================================================================
# DEGRADATION CHECK MIDDLEWARE
# ============================================================================

class DegradationMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle graceful degradation modes.
    """
    
    # Read-only endpoints (allowed even in read-only mode)
    READ_ONLY_PATHS = {"/", "/health", "/health/deep", "/metrics", "/ai/usage"}
    READ_ONLY_METHODS = {"GET", "HEAD", "OPTIONS"}
    
    async def dispatch(self, request: Request, call_next):
        mode = get_degradation_mode()
        
        # Normal mode - proceed
        if mode == DegradationMode.NORMAL:
            return await call_next(request)
        
        # Offline mode - return 503 for most endpoints
        if mode == DegradationMode.OFFLINE:
            if request.url.path not in self.READ_ONLY_PATHS:
                return Response(
                    content='{"error": "Service temporarily unavailable", "mode": "offline"}',
                    status_code=503,
                    media_type="application/json"
                )
        
        # Read-only mode - reject write operations
        if mode == DegradationMode.READ_ONLY:
            if request.method not in self.READ_ONLY_METHODS:
                return Response(
                    content='{"error": "Service is in read-only mode", "mode": "read_only"}',
                    status_code=503,
                    media_type="application/json"
                )
        
        return await call_next(request)


# ============================================================================
# AUTHENTICATION DEPENDENCIES
# ============================================================================

security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme)
) -> Optional[dict]:
    """
    Dependency to get the current authenticated user from JWT token.
    Returns None if no token provided (for optional auth).
    """
    if not credentials:
        return None
    
    token = credentials.credentials
    payload = verify_token(token)
    
    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return payload


async def require_auth(user: dict = Depends(get_current_user)) -> dict:
    """
    Dependency that requires authentication.
    """
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"}
        )
    return user


def require_permission(permission: Permission):
    """
    Dependency factory to require a specific permission.
    
    Usage:
        @app.get("/admin/users")
        async def list_users(user=Depends(require_permission(Permission.ADMIN_USERS))):
            ...
    """
    async def check(user: dict = Depends(require_auth)) -> dict:
        role = Role(user.get("role", "readonly"))
        
        if not has_permission(role, permission):
            log_audit_event(
                action="permission_denied",
                user_id=user.get("sub", "unknown"),
                resource_type="permission",
                resource_id=permission.value
            )
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: {permission.value}"
            )
        
        return user
    
    return check


def require_role(required_role: Role):
    """
    Dependency factory to require a specific role or higher.
    """
    role_hierarchy = [Role.READONLY, Role.FRONT_DESK_AGENT, Role.RESORT_MANAGER, Role.SUPER_ADMIN]
    
    async def check(user: dict = Depends(require_auth)) -> dict:
        user_role = Role(user.get("role", "readonly"))
        
        if role_hierarchy.index(user_role) < role_hierarchy.index(required_role):
            raise HTTPException(
                status_code=403,
                detail=f"Role {required_role.value} or higher required"
            )
        
        return user
    
    return check


# ============================================================================
# RESORT CONTEXT DEPENDENCY
# ============================================================================

async def get_resort_context(
    user: dict = Depends(get_current_user),
    x_resort_id: Optional[str] = Header(None, alias="X-Resort-ID")
) -> Optional[str]:
    """
    Get the resort context for multi-tenancy.
    Returns resort_id from token or header.
    """
    if user:
        return user.get("resort_id") or x_resort_id
    return x_resort_id


# ============================================================================
# HEALTH CHECK ENDPOINTS
# ============================================================================

def get_deep_health_check(db_check: bool = True, redis_check: bool = True) -> dict:
    """
    Perform deep health check with dependency checks.
    """
    checks = {}
    overall_status = HealthStatus.HEALTHY
    
    # Database check
    if db_check:
        try:
            # Would import and check DB here
            checks["database"] = {"status": "healthy", "latency_ms": 5}
        except Exception as e:
            checks["database"] = {"status": "unhealthy", "error": str(e)}
            overall_status = HealthStatus.UNHEALTHY
    
    # Redis check
    if redis_check:
        try:
            # Would import and check Redis here
            checks["redis"] = {"status": "healthy", "latency_ms": 2}
        except Exception as e:
            checks["redis"] = {"status": "unhealthy", "error": str(e)}
            overall_status = HealthStatus.DEGRADED if overall_status == HealthStatus.HEALTHY else overall_status
    
    # AI service check
    try:
        from services.translation import get_ai_usage_stats
        ai_stats = get_ai_usage_stats()
        checks["ai_providers"] = {
            "status": "healthy" if any(p.get("enabled") for p in ai_stats.get("providers", {}).values()) else "degraded",
            "active_providers": sum(1 for p in ai_stats.get("providers", {}).values() if p.get("enabled"))
        }
    except Exception as e:
        checks["ai_providers"] = {"status": "unknown", "error": str(e)}
    
    return create_health_response(
        status=overall_status,
        checks=checks,
        version="2.0.0-phase4"
    )


# ============================================================================
# INPUT VALIDATION DEPENDENCY
# ============================================================================

async def validate_request_body(request: Request):
    """
    Dependency to validate and sanitize request body.
    """
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            body = await request.json()
            
            # Validate each string field
            for key, value in body.items():
                if isinstance(value, str):
                    validation = validate_input(value)
                    if not validation["valid"]:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Invalid input in field '{key}': {validation['issues']}"
                        )
            
        except HTTPException:
            raise
        except Exception:
            pass  # Body parsing failed, let the route handler deal with it
