"""
In-Memory Event Bus for Lean MVP Architecture
==============================================

Replaces Redis Pub/Sub with asyncio-based in-memory event handling.
Suitable for single-instance deployments up to 10K users.

Features:
- Async event publishing and subscription
- Topic-based routing
- No external dependencies
- Zero latency (in-process)

Upgrade Path: When scaling beyond single instance, swap to Redis.
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Callable, Any, Optional
from collections import defaultdict
from dataclasses import dataclass, field
import json


@dataclass
class Event:
    """Represents an event in the system."""
    topic: str
    payload: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    event_id: str = field(default_factory=lambda: f"evt_{datetime.utcnow().timestamp()}")


class InMemoryEventBus:
    """
    In-memory event bus using asyncio queues.
    
    Replaces Redis Pub/Sub for single-instance deployments.
    Thread-safe within asyncio context.
    """
    
    def __init__(self, max_queue_size: int = 1000):
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._queue: asyncio.Queue = None
        self._running = False
        self._max_queue_size = max_queue_size
        self._stats = {
            "published": 0,
            "delivered": 0,
            "errors": 0
        }
    
    async def start(self):
        """Start the event bus processor."""
        if self._running:
            return
        
        self._queue = asyncio.Queue(maxsize=self._max_queue_size)
        self._running = True
        asyncio.create_task(self._process_events())
    
    async def stop(self):
        """Stop the event bus processor."""
        self._running = False
        if self._queue:
            # Process remaining events
            while not self._queue.empty():
                await asyncio.sleep(0.01)
    
    def subscribe(self, topic: str, handler: Callable):
        """
        Subscribe to a topic with a handler function.
        
        Args:
            topic: Topic name (e.g., "message.incoming", "guest.created")
            handler: Async function to call when event received
        """
        self._subscribers[topic].append(handler)
    
    def unsubscribe(self, topic: str, handler: Callable):
        """Remove a handler from a topic."""
        if topic in self._subscribers:
            self._subscribers[topic] = [h for h in self._subscribers[topic] if h != handler]
    
    async def publish(self, topic: str, payload: Dict[str, Any]):
        """
        Publish an event to a topic.
        
        Args:
            topic: Topic name
            payload: Event data
        """
        if not self._queue:
            await self.start()
        
        event = Event(topic=topic, payload=payload)
        
        try:
            self._queue.put_nowait(event)
            self._stats["published"] += 1
        except asyncio.QueueFull:
            # Drop oldest event if queue is full (should never happen at MVP scale)
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(event)
            except:
                self._stats["errors"] += 1
    
    async def _process_events(self):
        """Background task to process events from the queue."""
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0
                )
                await self._deliver_event(event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"⚠️ Event bus error: {e}")
                self._stats["errors"] += 1
    
    async def _deliver_event(self, event: Event):
        """Deliver event to all subscribers."""
        handlers = self._subscribers.get(event.topic, [])
        
        # Also check wildcard subscriptions
        wildcard_handlers = self._subscribers.get("*", [])
        all_handlers = handlers + wildcard_handlers
        
        for handler in all_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
                self._stats["delivered"] += 1
            except Exception as e:
                print(f"⚠️ Handler error for {event.topic}: {e}")
                self._stats["errors"] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get event bus statistics."""
        return {
            "running": self._running,
            "queue_size": self._queue.qsize() if self._queue else 0,
            "topics": list(self._subscribers.keys()),
            "subscriber_count": sum(len(h) for h in self._subscribers.values()),
            "size": self._queue.qsize() if self._queue else 0,  # Alias for compatibility
            **self._stats
        }


# Global event bus instance
event_bus = InMemoryEventBus()


# ============================================================================
# Standard Topics
# ============================================================================

class Topics:
    """Standard event topics."""
    MESSAGE_INCOMING = "message.incoming"
    MESSAGE_OUTGOING = "message.outgoing"
    MESSAGE_SENT = "message.sent"
    GUEST_CREATED = "guest.created"
    GUEST_UPDATED = "guest.updated"
    THREAD_CREATED = "thread.created"
    THREAD_SLA_WARNING = "thread.sla.warning"
    THREAD_SLA_BREACH = "thread.sla.breach"
    AI_SUGGESTION = "ai.suggestion"
    SYSTEM_HEALTH = "system.health"


# ============================================================================
# In-Memory Cache (Replaces Redis L2)
# ============================================================================

class InMemoryCache:
    """
    Simple in-memory cache with TTL support.
    Replaces Redis for MVP single-instance deployment.
    """
    
    def __init__(self, max_size: int = 10000, default_ttl: int = 300):
        self._cache: Dict[str, Dict] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._stats = {"hits": 0, "misses": 0, "sets": 0}
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        if key not in self._cache:
            self._stats["misses"] += 1
            return None
        
        entry = self._cache[key]
        
        # Check TTL
        if datetime.utcnow().timestamp() > entry["expires"]:
            del self._cache[key]
            self._stats["misses"] += 1
            return None
        
        self._stats["hits"] += 1
        return entry["value"]
    
    def set(self, key: str, value: Any, ttl: int = None):
        """Set value in cache with TTL."""
        ttl = ttl or self._default_ttl
        
        # Enforce max size (simple eviction: remove oldest)
        if len(self._cache) >= self._max_size:
            oldest = min(self._cache.keys(), key=lambda k: self._cache[k]["created"])
            del self._cache[oldest]
        
        self._cache[key] = {
            "value": value,
            "created": datetime.utcnow().timestamp(),
            "expires": datetime.utcnow().timestamp() + ttl
        }
        self._stats["sets"] += 1
    
    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False
    
    def clear(self):
        """Clear all cache entries."""
        self._cache.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0
        
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hit_rate_percent": round(hit_rate, 2),
            **self._stats
        }


# Global cache instance
cache = InMemoryCache()


# ============================================================================
# In-Memory Rate Limiter (Replaces Redis)
# ============================================================================

class InMemoryRateLimiter:
    """
    Token bucket rate limiter using in-memory storage.
    Replaces Redis-based rate limiting for MVP.
    """
    
    def __init__(self):
        self._buckets: Dict[str, Dict] = {}
    
    def is_allowed(self, key: str, max_requests: int = 100, window_seconds: int = 60) -> bool:
        """
        Check if request is allowed under rate limit.
        
        Args:
            key: Identifier (e.g., IP address, API key)
            max_requests: Maximum requests per window
            window_seconds: Time window in seconds
        
        Returns:
            True if allowed, False if rate limited
        """
        now = datetime.utcnow().timestamp()
        
        if key not in self._buckets:
            self._buckets[key] = {
                "tokens": max_requests - 1,
                "last_update": now
            }
            return True
        
        bucket = self._buckets[key]
        elapsed = now - bucket["last_update"]
        
        # Refill tokens
        refill = int(elapsed * max_requests / window_seconds)
        bucket["tokens"] = min(max_requests, bucket["tokens"] + refill)
        bucket["last_update"] = now
        
        if bucket["tokens"] > 0:
            bucket["tokens"] -= 1
            return True
        
        return False
    
    def cleanup(self):
        """Remove stale buckets (older than 10 minutes)."""
        now = datetime.utcnow().timestamp()
        stale_keys = [
            k for k, v in self._buckets.items()
            if now - v["last_update"] > 600
        ]
        for key in stale_keys:
            del self._buckets[key]


# Global rate limiter
rate_limiter = InMemoryRateLimiter()
