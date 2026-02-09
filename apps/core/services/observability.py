"""
Observability Service for Phase 4: Enterprise Robustness
=========================================================

Handles:
- Structured logging with correlation IDs
- Metrics collection (Golden Signals)
- Distributed tracing support
- PII masking in logs
"""
import os
import json
import time
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable
from functools import wraps
from contextvars import ContextVar
import uuid

# ============================================================================
# CONTEXT VARIABLES (Thread-safe request context)
# ============================================================================

# Correlation ID for request tracing
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
request_start_time_var: ContextVar[float] = ContextVar("request_start_time", default=0.0)

# ============================================================================
# PII MASKING
# ============================================================================

# Patterns for PII detection and masking
PII_PATTERNS = {
    "email": (r'[\w.+-]+@[\w-]+\.[\w.-]+', '[EMAIL_REDACTED]'),
    "phone": (r'\+?\d{10,15}', '[PHONE_REDACTED]'),
    "credit_card": (r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', '[CC_REDACTED]'),
    "ssn": (r'\b\d{3}-\d{2}-\d{4}\b', '[SSN_REDACTED]'),
    "passport": (r'\b[A-Z]{1,2}\d{6,9}\b', '[PASSPORT_REDACTED]'),
}

# Fields that contain PII and should be fully redacted
PII_FIELDS = {
    "password", "secret", "token", "api_key", "apikey", "authorization",
    "credit_card", "card_number", "cvv", "ssn", "passport_number",
    "date_of_birth", "dob", "social_security"
}


def mask_pii(value: Any, field_name: str = "") -> Any:
    """
    Mask PII in values for safe logging.
    """
    # Check if field name indicates PII
    if field_name.lower() in PII_FIELDS:
        return "[REDACTED]"
    
    if isinstance(value, str):
        masked = value
        for pattern_name, (pattern, replacement) in PII_PATTERNS.items():
            masked = re.sub(pattern, replacement, masked)
        return masked
    
    if isinstance(value, dict):
        return {k: mask_pii(v, k) for k, v in value.items()}
    
    if isinstance(value, list):
        return [mask_pii(item) for item in value]
    
    return value


# ============================================================================
# STRUCTURED LOGGING
# ============================================================================

class StructuredLogger:
    """
    JSON-formatted structured logger with PII masking and correlation ID support.
    """
    
    def __init__(self, name: str, level: int = logging.INFO):
        self.name = name
        self.level = level
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        
        # Remove existing handlers
        self.logger.handlers = []
        
        # Add structured JSON handler
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredFormatter())
        self.logger.addHandler(handler)
    
    def _log(self, level: int, message: str, **kwargs):
        """Internal log method with structured data."""
        extra = {
            "correlation_id": correlation_id_var.get(""),
            "service": self.name,
            "extra_data": mask_pii(kwargs)
        }
        self.logger.log(level, message, extra=extra)
    
    def debug(self, message: str, **kwargs):
        self._log(logging.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs):
        self._log(logging.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        self._log(logging.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs):
        self._log(logging.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        self._log(logging.CRITICAL, message, **kwargs)


class StructuredFormatter(logging.Formatter):
    """Format log records as JSON."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", ""),
            "service": getattr(record, "service", ""),
        }
        
        # Add extra data if present
        extra_data = getattr(record, "extra_data", {})
        if extra_data:
            log_entry["data"] = extra_data
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_entry)


# Default logger instance
logger = StructuredLogger("resortOS")


# ============================================================================
# METRICS COLLECTION (Golden Signals)
# ============================================================================

class MetricsCollector:
    """
    Collects Golden Signals metrics:
    - Latency: Response time distributions
    - Traffic: Request counts
    - Errors: Error counts and rates
    - Saturation: Resource utilization
    """
    
    def __init__(self):
        self._latencies: Dict[str, List[float]] = {}  # endpoint -> latencies
        self._request_counts: Dict[str, int] = {}  # endpoint -> count
        self._error_counts: Dict[str, int] = {}  # endpoint -> error count
        self._status_codes: Dict[str, Dict[int, int]] = {}  # endpoint -> {status: count}
        self._start_time = datetime.utcnow()
    
    def record_request(
        self,
        endpoint: str,
        latency_ms: float,
        status_code: int,
        method: str = "GET"
    ):
        """Record a completed request."""
        key = f"{method}:{endpoint}"
        
        # Record latency
        if key not in self._latencies:
            self._latencies[key] = []
        self._latencies[key].append(latency_ms)
        
        # Trim to last 1000 entries per endpoint
        if len(self._latencies[key]) > 1000:
            self._latencies[key] = self._latencies[key][-1000:]
        
        # Record request count
        self._request_counts[key] = self._request_counts.get(key, 0) + 1
        
        # Record status code
        if key not in self._status_codes:
            self._status_codes[key] = {}
        self._status_codes[key][status_code] = self._status_codes[key].get(status_code, 0) + 1
        
        # Record error if applicable
        if status_code >= 400:
            self._error_counts[key] = self._error_counts.get(key, 0) + 1
    
    def get_latency_stats(self, endpoint: str = None) -> Dict[str, Any]:
        """Get latency statistics (p50, p95, p99)."""
        def calc_percentiles(values: List[float]) -> Dict[str, float]:
            if not values:
                return {"p50": 0, "p95": 0, "p99": 0, "avg": 0}
            
            sorted_vals = sorted(values)
            n = len(sorted_vals)
            
            return {
                "p50": sorted_vals[int(n * 0.5)],
                "p95": sorted_vals[int(n * 0.95)] if n > 1 else sorted_vals[0],
                "p99": sorted_vals[int(n * 0.99)] if n > 1 else sorted_vals[0],
                "avg": sum(values) / n,
                "count": n
            }
        
        if endpoint:
            return calc_percentiles(self._latencies.get(endpoint, []))
        
        return {
            key: calc_percentiles(values)
            for key, values in self._latencies.items()
        }
    
    def get_traffic_stats(self) -> Dict[str, Any]:
        """Get traffic statistics."""
        uptime_seconds = (datetime.utcnow() - self._start_time).total_seconds()
        total_requests = sum(self._request_counts.values())
        
        return {
            "total_requests": total_requests,
            "requests_per_second": total_requests / max(uptime_seconds, 1),
            "by_endpoint": self._request_counts.copy(),
            "uptime_seconds": uptime_seconds
        }
    
    def get_error_stats(self) -> Dict[str, Any]:
        """Get error statistics."""
        total_requests = sum(self._request_counts.values())
        total_errors = sum(self._error_counts.values())
        
        return {
            "total_errors": total_errors,
            "error_rate": total_errors / max(total_requests, 1) * 100,
            "by_endpoint": self._error_counts.copy(),
            "status_codes": {
                endpoint: dict(codes)
                for endpoint, codes in self._status_codes.items()
            }
        }
    
    def get_golden_signals(self) -> Dict[str, Any]:
        """Get all Golden Signals in one call."""
        return {
            "latency": self.get_latency_stats(),
            "traffic": self.get_traffic_stats(),
            "errors": self.get_error_stats(),
            "saturation": self._get_saturation()
        }
    
    def _get_saturation(self) -> Dict[str, Any]:
        """Get resource saturation metrics."""
        import sys
        
        try:
            import psutil
            process = psutil.Process()
            
            return {
                "memory_percent": process.memory_percent(),
                "cpu_percent": process.cpu_percent(),
                "open_files": len(process.open_files()),
                "threads": process.num_threads()
            }
        except ImportError:
            return {
                "memory_mb": sys.getsizeof(self._latencies) / 1024 / 1024,
                "note": "Install psutil for detailed metrics"
            }


# Global metrics collector
metrics = MetricsCollector()


# ============================================================================
# REQUEST TRACING DECORATOR
# ============================================================================

def trace_request(endpoint_name: str = None):
    """
    Decorator to trace requests with correlation ID and metrics.
    """
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Generate or use existing correlation ID
            corr_id = correlation_id_var.get() or str(uuid.uuid4())[:8]
            correlation_id_var.set(corr_id)
            
            start_time = time.time()
            request_start_time_var.set(start_time)
            
            status_code = 200
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status_code = 500
                logger.error(f"Request failed: {str(e)}", endpoint=endpoint_name)
                raise
            finally:
                latency_ms = (time.time() - start_time) * 1000
                metrics.record_request(
                    endpoint=endpoint_name or func.__name__,
                    latency_ms=latency_ms,
                    status_code=status_code
                )
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            corr_id = correlation_id_var.get() or str(uuid.uuid4())[:8]
            correlation_id_var.set(corr_id)
            
            start_time = time.time()
            status_code = 200
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                status_code = 500
                logger.error(f"Request failed: {str(e)}", endpoint=endpoint_name)
                raise
            finally:
                latency_ms = (time.time() - start_time) * 1000
                metrics.record_request(
                    endpoint=endpoint_name or func.__name__,
                    latency_ms=latency_ms,
                    status_code=status_code
                )
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# ============================================================================
# HEALTH CHECK UTILITIES
# ============================================================================

class HealthStatus:
    """Health check result."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


def create_health_response(
    status: str,
    checks: Dict[str, Any],
    version: str = "1.0.0"
) -> Dict[str, Any]:
    """Create a standardized health check response."""
    return {
        "status": status,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": version,
        "checks": checks,
        "uptime_seconds": (datetime.utcnow() - metrics._start_time).total_seconds()
    }


# ============================================================================
# ALERT THRESHOLDS
# ============================================================================

class AlertLevel:
    """Alert severity levels."""
    P1_CRITICAL = "P1"  # Service down - immediate
    P2_HIGH = "P2"      # Error rate > 5%
    P3_MEDIUM = "P3"    # Latency spike
    P4_LOW = "P4"       # Capacity warning


ALERT_THRESHOLDS = {
    "error_rate_p2": 5.0,      # Error rate > 5% = P2
    "latency_p95_ms": 500,     # p95 latency > 500ms = P3
    "latency_p99_ms": 1000,    # p99 latency > 1000ms = P2
    "memory_percent": 80,      # Memory > 80% = P3
    "cpu_percent": 90,         # CPU > 90% = P2
}


def check_alerts() -> List[Dict[str, Any]]:
    """Check current metrics against alert thresholds."""
    alerts = []
    golden = metrics.get_golden_signals()
    
    # Check error rate
    error_rate = golden["errors"]["error_rate"]
    if error_rate > ALERT_THRESHOLDS["error_rate_p2"]:
        alerts.append({
            "level": AlertLevel.P2_HIGH,
            "type": "error_rate",
            "message": f"Error rate {error_rate:.1f}% exceeds threshold",
            "value": error_rate,
            "threshold": ALERT_THRESHOLDS["error_rate_p2"]
        })
    
    # Check latencies
    for endpoint, stats in golden["latency"].items():
        if stats.get("p95", 0) > ALERT_THRESHOLDS["latency_p95_ms"]:
            alerts.append({
                "level": AlertLevel.P3_MEDIUM,
                "type": "latency_p95",
                "message": f"p95 latency for {endpoint} is {stats['p95']:.0f}ms",
                "value": stats["p95"],
                "threshold": ALERT_THRESHOLDS["latency_p95_ms"],
                "endpoint": endpoint
            })
    
    # Check saturation
    sat = golden.get("saturation", {})
    if sat.get("memory_percent", 0) > ALERT_THRESHOLDS["memory_percent"]:
        alerts.append({
            "level": AlertLevel.P3_MEDIUM,
            "type": "memory",
            "message": f"Memory usage at {sat['memory_percent']:.1f}%",
            "value": sat["memory_percent"],
            "threshold": ALERT_THRESHOLDS["memory_percent"]
        })
    
    return alerts


# ============================================================================
# OBSERVABILITY DASHBOARD DATA
# ============================================================================

def get_observability_dashboard() -> Dict[str, Any]:
    """Get comprehensive observability data for dashboards."""
    return {
        "golden_signals": metrics.get_golden_signals(),
        "alerts": check_alerts(),
        "health": {
            "status": HealthStatus.HEALTHY if not check_alerts() else HealthStatus.DEGRADED
        }
    }
