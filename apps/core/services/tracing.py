"""
Distributed Tracing Service for Phase 4: Observability
=======================================================

Implements OpenTelemetry-compatible distributed tracing:
- Trace ID propagation across services
- Span creation and context management
- Performance timing
- Integration with Cloud Trace/Jaeger

Note: This is a lightweight implementation that can be
replaced with full OpenTelemetry SDK in production.
"""
import os
import time
import uuid
import json
from datetime import datetime
from typing import Dict, Any, Optional, List
from contextvars import ContextVar
from functools import wraps

# ============================================================================
# CONFIGURATION
# ============================================================================

SERVICE_NAME = os.getenv("SERVICE_NAME", "resortOS-core")
TRACE_ENABLED = os.getenv("TRACE_ENABLED", "true").lower() == "true"
TRACE_SAMPLE_RATE = float(os.getenv("TRACE_SAMPLE_RATE", "1.0"))  # 1.0 = 100%
TRACE_EXPORT_ENDPOINT = os.getenv("TRACE_EXPORT_ENDPOINT", "")  # e.g., Jaeger/OTLP


# Context variables for request-scoped tracing
_current_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)
_current_span_id: ContextVar[Optional[str]] = ContextVar("span_id", default=None)
_current_spans: ContextVar[List] = ContextVar("spans", default=[])


# ============================================================================
# TRACE ID MANAGEMENT
# ============================================================================

def generate_trace_id() -> str:
    """Generate a unique trace ID (32 hex chars like OpenTelemetry)."""
    return uuid.uuid4().hex


def generate_span_id() -> str:
    """Generate a unique span ID (16 hex chars)."""
    return uuid.uuid4().hex[:16]


def get_current_trace_id() -> Optional[str]:
    """Get the current trace ID from context."""
    return _current_trace_id.get()


def get_current_span_id() -> Optional[str]:
    """Get the current span ID from context."""
    return _current_span_id.get()


def set_trace_context(trace_id: str, span_id: str = None):
    """Set the trace context for the current request."""
    _current_trace_id.set(trace_id)
    if span_id:
        _current_span_id.set(span_id)


def clear_trace_context():
    """Clear trace context at end of request."""
    _current_trace_id.set(None)
    _current_span_id.set(None)
    _current_spans.set([])


# ============================================================================
# SPAN MANAGEMENT
# ============================================================================

class Span:
    """
    Represents a unit of work within a trace.
    Compatible with OpenTelemetry span structure.
    """
    
    def __init__(
        self,
        name: str,
        trace_id: str = None,
        parent_span_id: str = None,
        kind: str = "internal"  # internal, server, client, producer, consumer
    ):
        self.name = name
        self.trace_id = trace_id or get_current_trace_id() or generate_trace_id()
        self.span_id = generate_span_id()
        self.parent_span_id = parent_span_id or get_current_span_id()
        self.kind = kind
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.status = "OK"
        self.attributes: Dict[str, Any] = {
            "service.name": SERVICE_NAME
        }
        self.events: List[Dict] = []
    
    def set_attribute(self, key: str, value: Any):
        """Add an attribute to the span."""
        self.attributes[key] = value
    
    def add_event(self, name: str, attributes: Dict = None):
        """Record an event within the span."""
        self.events.append({
            "name": name,
            "timestamp": datetime.utcnow().isoformat(),
            "attributes": attributes or {}
        })
    
    def set_status(self, status: str, description: str = None):
        """Set the span status (OK, ERROR)."""
        self.status = status
        if description:
            self.attributes["error.message"] = description
    
    def end(self):
        """End the span and record duration."""
        self.end_time = time.time()
    
    @property
    def duration_ms(self) -> float:
        """Get span duration in milliseconds."""
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert span to dictionary for export."""
        return {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent_span_id,
            "name": self.name,
            "kind": self.kind,
            "startTime": datetime.fromtimestamp(self.start_time).isoformat(),
            "endTime": datetime.fromtimestamp(self.end_time).isoformat() if self.end_time else None,
            "durationMs": round(self.duration_ms, 2),
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events
        }
    
    def __enter__(self):
        """Context manager entry - set as current span."""
        _current_span_id.set(self.span_id)
        _current_trace_id.set(self.trace_id)
        spans = _current_spans.get() or []
        spans.append(self)
        _current_spans.set(spans)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - end span and restore parent."""
        if exc_type:
            self.set_status("ERROR", str(exc_val))
        self.end()
        
        spans = _current_spans.get() or []
        if spans:
            spans.pop()
        if spans:
            _current_span_id.set(spans[-1].span_id)
        else:
            _current_span_id.set(None)


# ============================================================================
# TRACING DECORATORS
# ============================================================================

def trace(name: str = None, kind: str = "internal"):
    """
    Decorator to automatically trace a function.
    
    Usage:
        @trace("db_query")
        def get_guest(guest_id: str):
            ...
    """
    def decorator(func):
        span_name = name or f"{func.__module__}.{func.__name__}"
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not TRACE_ENABLED:
                return func(*args, **kwargs)
            
            with Span(span_name, kind=kind) as span:
                # Add function arguments as attributes
                span.set_attribute("function.name", func.__name__)
                if args:
                    span.set_attribute("function.args_count", len(args))
                
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.set_status("ERROR", str(e))
                    raise
        
        return wrapper
    return decorator


def trace_async(name: str = None, kind: str = "internal"):
    """Async version of trace decorator."""
    def decorator(func):
        span_name = name or f"{func.__module__}.{func.__name__}"
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not TRACE_ENABLED:
                return await func(*args, **kwargs)
            
            with Span(span_name, kind=kind) as span:
                span.set_attribute("function.name", func.__name__)
                
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.set_status("ERROR", str(e))
                    raise
        
        return wrapper
    return decorator


# ============================================================================
# TRACE COLLECTION & EXPORT
# ============================================================================

# In-memory trace storage (replace with proper exporter in production)
_trace_buffer: List[Dict] = []
_max_buffer_size = 1000


def record_span(span: Span):
    """Record a completed span to the buffer."""
    global _trace_buffer
    
    if len(_trace_buffer) >= _max_buffer_size:
        # Drop oldest traces
        _trace_buffer = _trace_buffer[100:]
    
    _trace_buffer.append(span.to_dict())


def get_recent_traces(limit: int = 100) -> List[Dict]:
    """Get recent traces for debugging."""
    return _trace_buffer[-limit:]


def get_trace_by_id(trace_id: str) -> List[Dict]:
    """Get all spans for a specific trace."""
    return [s for s in _trace_buffer if s["traceId"] == trace_id]


def clear_trace_buffer():
    """Clear the trace buffer."""
    global _trace_buffer
    _trace_buffer = []


def get_tracing_stats() -> Dict[str, Any]:
    """Get tracing statistics."""
    if not _trace_buffer:
        return {
            "enabled": TRACE_ENABLED,
            "sample_rate": TRACE_SAMPLE_RATE,
            "buffer_size": 0,
            "spans_recorded": 0
        }
    
    # Calculate stats
    durations = [s["durationMs"] for s in _trace_buffer if s.get("durationMs")]
    errors = [s for s in _trace_buffer if s.get("status") == "ERROR"]
    
    return {
        "enabled": TRACE_ENABLED,
        "sample_rate": TRACE_SAMPLE_RATE,
        "buffer_size": len(_trace_buffer),
        "spans_recorded": len(_trace_buffer),
        "error_count": len(errors),
        "avg_duration_ms": round(sum(durations) / len(durations), 2) if durations else 0,
        "p95_duration_ms": round(sorted(durations)[int(len(durations) * 0.95)], 2) if durations else 0
    }


# ============================================================================
# HTTP HEADER PROPAGATION (W3C Trace Context)
# ============================================================================

def extract_trace_from_headers(headers: Dict[str, str]) -> Optional[str]:
    """
    Extract trace ID from incoming HTTP headers.
    Supports W3C Trace Context format.
    """
    # W3C Trace Context header
    traceparent = headers.get("traceparent", "")
    if traceparent:
        # Format: 00-{trace_id}-{span_id}-{flags}
        parts = traceparent.split("-")
        if len(parts) >= 2:
            return parts[1]
    
    # Fallback to custom header
    return headers.get("x-trace-id")


def inject_trace_to_headers(headers: Dict[str, str] = None) -> Dict[str, str]:
    """
    Inject trace ID into outgoing HTTP headers.
    """
    headers = headers or {}
    trace_id = get_current_trace_id()
    span_id = get_current_span_id()
    
    if trace_id and span_id:
        # W3C Trace Context format
        headers["traceparent"] = f"00-{trace_id}-{span_id}-01"
        headers["x-trace-id"] = trace_id
    
    return headers
