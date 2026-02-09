"""
Resilience Service for Phase 4: Enterprise Robustness
======================================================

Handles:
- Circuit breaker pattern
- Retry policies with exponential backoff
- Graceful degradation
- Dead letter queue simulation
- Idempotency key management
"""
import os
import time
import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable, List
from functools import wraps
from enum import Enum
import random

# ============================================================================
# CIRCUIT BREAKER
# ============================================================================

class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, reject requests
    HALF_OPEN = "half_open" # Testing if recovered


class CircuitBreaker:
    """
    Circuit breaker implementation for fault tolerance.
    
    States:
    - CLOSED: Normal operation, tracking failures
    - OPEN: Too many failures, rejecting all requests
    - HALF_OPEN: Testing if service recovered
    
    Usage:
        breaker = CircuitBreaker("ai_service", failure_threshold=5)
        
        try:
            result = await breaker.call(ai_function, args)
        except CircuitOpenError:
            # Use fallback
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        half_open_max_calls: int = 3
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._half_open_calls = 0
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state, handling automatic transition from OPEN."""
        if self._state == CircuitState.OPEN:
            if self._last_failure_time:
                elapsed = (datetime.utcnow() - self._last_failure_time).total_seconds()
                if elapsed >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    print(f"⚡ Circuit {self.name}: OPEN → HALF_OPEN (recovery attempt)")
        
        return self._state
    
    def _record_success(self):
        """Record a successful call."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.half_open_max_calls:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                print(f"✅ Circuit {self.name}: HALF_OPEN → CLOSED (recovered)")
        else:
            self._failure_count = max(0, self._failure_count - 1)
    
    def _record_failure(self):
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = datetime.utcnow()
        
        if self._state == CircuitState.HALF_OPEN:
            # Failed during recovery, back to OPEN
            self._state = CircuitState.OPEN
            print(f"🔴 Circuit {self.name}: HALF_OPEN → OPEN (recovery failed)")
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            print(f"🔴 Circuit {self.name}: CLOSED → OPEN (threshold reached)")
    
    async def call(self, func: Callable, *args, **kwargs):
        """
        Execute function through circuit breaker.
        
        Raises:
            CircuitOpenError: If circuit is open
        """
        state = self.state  # Triggers automatic OPEN→HALF_OPEN if timeout passed
        
        if state == CircuitState.OPEN:
            raise CircuitOpenError(f"Circuit {self.name} is OPEN")
        
        if state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
        
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            self._record_success()
            return result
        
        except Exception as e:
            self._record_failure()
            raise
    
    def get_status(self) -> Dict[str, Any]:
        """Get circuit breaker status."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "last_failure": self._last_failure_time.isoformat() if self._last_failure_time else None,
            "recovery_timeout_seconds": self.recovery_timeout
        }


class CircuitOpenError(Exception):
    """Raised when circuit is open and request is rejected."""
    pass


# Global circuit breakers registry
_circuit_breakers: Dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: int = 30
) -> CircuitBreaker:
    """Get or create a circuit breaker by name."""
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout
        )
    return _circuit_breakers[name]


def get_all_circuit_breakers() -> Dict[str, Dict]:
    """Get status of all circuit breakers."""
    return {
        name: breaker.get_status()
        for name, breaker in _circuit_breakers.items()
    }


# ============================================================================
# RETRY POLICY
# ============================================================================

class RetryPolicy:
    """
    Retry policy with exponential backoff and jitter.
    
    Usage:
        policy = RetryPolicy(max_retries=3, base_delay=1.0)
        result = await policy.execute(flaky_function, args)
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: tuple = (Exception,)
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions
    
    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay for retry attempt with exponential backoff."""
        delay = min(
            self.base_delay * (self.exponential_base ** attempt),
            self.max_delay
        )
        
        if self.jitter:
            # Add random jitter (0.5x to 1.5x of calculated delay)
            delay = delay * (0.5 + random.random())
        
        return delay
    
    async def execute(self, func: Callable, *args, **kwargs):
        """Execute function with retry policy."""
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)
            
            except self.retryable_exceptions as e:
                last_exception = e
                
                if attempt < self.max_retries:
                    delay = self._calculate_delay(attempt)
                    print(f"⏳ Retry {attempt + 1}/{self.max_retries} after {delay:.2f}s: {str(e)[:50]}")
                    await asyncio.sleep(delay)
                else:
                    print(f"❌ All {self.max_retries} retries exhausted")
        
        raise last_exception


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    retryable_exceptions: tuple = (Exception,)
):
    """Decorator to add retry policy to a function."""
    policy = RetryPolicy(
        max_retries=max_retries,
        base_delay=base_delay,
        retryable_exceptions=retryable_exceptions
    )
    
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await policy.execute(func, *args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            import asyncio
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(policy.execute(func, *args, **kwargs))
            finally:
                loop.close()
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# ============================================================================
# IDEMPOTENCY KEYS
# ============================================================================

# In-memory idempotency store (use Redis in production)
_idempotency_store: Dict[str, Dict[str, Any]] = {}
IDEMPOTENCY_TTL_SECONDS = 86400  # 24 hours


def generate_idempotency_key(
    operation: str,
    params: Dict[str, Any]
) -> str:
    """Generate a unique idempotency key."""
    content = f"{operation}:{sorted(params.items())}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def check_idempotency(key: str) -> Optional[Dict[str, Any]]:
    """
    Check if operation was already performed.
    
    Returns:
        Previous result if found, None otherwise
    """
    if key not in _idempotency_store:
        return None
    
    entry = _idempotency_store[key]
    
    # Check TTL
    created_at = datetime.fromisoformat(entry["created_at"])
    if (datetime.utcnow() - created_at).total_seconds() > IDEMPOTENCY_TTL_SECONDS:
        del _idempotency_store[key]
        return None
    
    return entry.get("result")


def store_idempotency(key: str, result: Any):
    """Store idempotency result."""
    _idempotency_store[key] = {
        "result": result,
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Cleanup old entries (simple LRU)
    if len(_idempotency_store) > 10000:
        oldest_keys = sorted(
            _idempotency_store.keys(),
            key=lambda k: _idempotency_store[k]["created_at"]
        )[:1000]
        for k in oldest_keys:
            del _idempotency_store[k]


def idempotent(operation_name: str):
    """Decorator to make a function idempotent."""
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            key = generate_idempotency_key(operation_name, kwargs)
            
            # Check for existing result
            cached = check_idempotency(key)
            if cached is not None:
                print(f"📦 Idempotent hit for {operation_name}")
                return cached
            
            # Execute and store
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            store_idempotency(key, result)
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            key = generate_idempotency_key(operation_name, kwargs)
            
            cached = check_idempotency(key)
            if cached is not None:
                return cached
            
            result = func(*args, **kwargs)
            store_idempotency(key, result)
            return result
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# ============================================================================
# DEAD LETTER QUEUE (In-Memory Simulation)
# ============================================================================

class DeadLetterQueue:
    """
    Dead letter queue for failed messages.
    In production, use Redis or a proper message broker.
    """
    
    def __init__(self, name: str, max_size: int = 1000):
        self.name = name
        self.max_size = max_size
        self._queue: List[Dict[str, Any]] = []
    
    def add(
        self,
        message: Any,
        error: str,
        original_queue: str = None,
        metadata: Dict = None
    ):
        """Add a failed message to DLQ."""
        entry = {
            "id": hashlib.md5(str(message).encode()).hexdigest()[:8],
            "message": message,
            "error": error,
            "original_queue": original_queue,
            "metadata": metadata or {},
            "failed_at": datetime.utcnow().isoformat(),
            "retry_count": 0
        }
        
        self._queue.append(entry)
        
        # Trim if too large (FIFO eviction)
        if len(self._queue) > self.max_size:
            self._queue = self._queue[-self.max_size:]
        
        print(f"💀 DLQ [{self.name}]: Added message {entry['id']} - {error[:50]}")
    
    def get_all(self) -> List[Dict]:
        """Get all messages in DLQ."""
        return self._queue.copy()
    
    def retry(self, message_id: str, handler: Callable) -> bool:
        """Retry a specific message."""
        for i, entry in enumerate(self._queue):
            if entry["id"] == message_id:
                try:
                    handler(entry["message"])
                    self._queue.pop(i)
                    print(f"✅ DLQ [{self.name}]: Successfully retried {message_id}")
                    return True
                except Exception as e:
                    entry["retry_count"] += 1
                    entry["last_error"] = str(e)
                    entry["last_retry"] = datetime.utcnow().isoformat()
                    print(f"❌ DLQ [{self.name}]: Retry failed for {message_id}")
                    return False
        return False
    
    def clear(self):
        """Clear all messages from DLQ."""
        count = len(self._queue)
        self._queue = []
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get DLQ statistics."""
        return {
            "name": self.name,
            "size": len(self._queue),
            "max_size": self.max_size,
            "oldest": self._queue[0]["failed_at"] if self._queue else None,
            "newest": self._queue[-1]["failed_at"] if self._queue else None
        }


# Global DLQ instances
_dlqs: Dict[str, DeadLetterQueue] = {}


def get_dlq(name: str) -> DeadLetterQueue:
    """Get or create a dead letter queue."""
    if name not in _dlqs:
        _dlqs[name] = DeadLetterQueue(name)
    return _dlqs[name]


# ============================================================================
# GRACEFUL DEGRADATION
# ============================================================================

class FallbackResponse:
    """Container for fallback responses when services are degraded."""
    
    # AI service fallback templates
    AI_TEMPLATES = {
        "greeting": "Thank you for contacting Club Med! A team member will respond shortly.",
        "booking": "For booking inquiries, please contact our reservations team or visit clubmed.com",
        "spa": "Our spa services are available from 9 AM to 8 PM. Please visit the front desk for appointments.",
        "dining": "Our restaurants serve breakfast (7-10 AM), lunch (12-2 PM), and dinner (7-10 PM).",
        "activities": "Please check the daily activity board in the main lobby for today's schedule.",
        "default": "Thank you for your message. Our team will respond as soon as possible."
    }
    
    @classmethod
    def get_ai_fallback(cls, intent: str = "default") -> str:
        """Get fallback response when AI is unavailable."""
        return cls.AI_TEMPLATES.get(intent, cls.AI_TEMPLATES["default"])
    
    @classmethod
    def detect_intent(cls, message: str) -> str:
        """Simple intent detection for fallback responses."""
        message_lower = message.lower()
        
        if any(word in message_lower for word in ["hello", "hi", "hey", "good"]):
            return "greeting"
        if any(word in message_lower for word in ["book", "reservation", "reserve"]):
            return "booking"
        if any(word in message_lower for word in ["spa", "massage", "treatment"]):
            return "spa"
        if any(word in message_lower for word in ["food", "restaurant", "dinner", "lunch", "breakfast"]):
            return "dining"
        if any(word in message_lower for word in ["activity", "activities", "excursion", "tour"]):
            return "activities"
        
        return "default"


class DegradationMode(Enum):
    """Service degradation modes."""
    NORMAL = "normal"
    READ_ONLY = "read_only"
    OFFLINE = "offline"


# Global degradation state
_degradation_mode = DegradationMode.NORMAL


def set_degradation_mode(mode: DegradationMode):
    """Set the current degradation mode."""
    global _degradation_mode
    _degradation_mode = mode
    print(f"⚠️ Degradation mode set to: {mode.value}")


def get_degradation_mode() -> DegradationMode:
    """Get the current degradation mode."""
    return _degradation_mode


def is_read_only() -> bool:
    """Check if system is in read-only mode."""
    return _degradation_mode in (DegradationMode.READ_ONLY, DegradationMode.OFFLINE)


def is_offline() -> bool:
    """Check if system is in offline mode."""
    return _degradation_mode == DegradationMode.OFFLINE


# ============================================================================
# RESILIENCE STATS
# ============================================================================

def get_resilience_stats() -> Dict[str, Any]:
    """Get comprehensive resilience statistics."""
    return {
        "circuit_breakers": get_all_circuit_breakers(),
        "dead_letter_queues": {
            name: dlq.get_stats() for name, dlq in _dlqs.items()
        },
        "idempotency": {
            "cached_operations": len(_idempotency_store)
        },
        "degradation_mode": _degradation_mode.value
    }
