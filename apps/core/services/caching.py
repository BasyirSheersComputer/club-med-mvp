"""
Caching Service for Phase 4: Performance & Scalability
=======================================================

Implements multi-layer caching strategy:
- L1: In-memory cache (per-instance)
- L2: Redis cache (shared across instances)
- L3: CDN for static assets (handled externally)

Features:
- TTL-based expiration
- Cache invalidation patterns
- Cache warming utilities
- Performance metrics
"""
import os
import time
import json
import hashlib
from datetime import datetime, timedelta
from typing import Any, Optional, Dict, List, Callable
from functools import wraps
from collections import OrderedDict

# ============================================================================
# CONFIGURATION
# ============================================================================

L1_MAX_SIZE = int(os.getenv("L1_CACHE_MAX_SIZE", "1000"))
L1_DEFAULT_TTL = int(os.getenv("L1_CACHE_TTL", "60"))  # 1 minute
L2_DEFAULT_TTL = int(os.getenv("L2_CACHE_TTL", "300"))  # 5 minutes

# Redis connection (reuse from app)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")


# ============================================================================
# L1: IN-MEMORY CACHE (Per Instance)
# ============================================================================

class L1Cache:
    """
    Fast in-memory cache using OrderedDict for LRU eviction.
    Per-instance, no sharing between replicas.
    """
    
    def __init__(self, max_size: int = L1_MAX_SIZE, default_ttl: int = L1_DEFAULT_TTL):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict = OrderedDict()
        self._expires: Dict[str, float] = {}
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "sets": 0
        }
    
    def _is_expired(self, key: str) -> bool:
        if key not in self._expires:
            return True
        return time.time() > self._expires[key]
    
    def _evict_expired(self):
        """Remove expired entries."""
        now = time.time()
        expired_keys = [k for k, exp in self._expires.items() if now > exp]
        for key in expired_keys:
            self._cache.pop(key, None)
            self._expires.pop(key, None)
    
    def _enforce_size_limit(self):
        """Evict oldest entries if over size limit."""
        while len(self._cache) > self.max_size:
            oldest_key, _ = self._cache.popitem(last=False)
            self._expires.pop(oldest_key, None)
            self._stats["evictions"] += 1
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache, returns None if not found or expired."""
        if key not in self._cache or self._is_expired(key):
            self._stats["misses"] += 1
            if key in self._cache:
                del self._cache[key]
                del self._expires[key]
            return None
        
        # Move to end (most recently used)
        self._cache.move_to_end(key)
        self._stats["hits"] += 1
        return self._cache[key]
    
    def set(self, key: str, value: Any, ttl: int = None):
        """Set value in cache with TTL."""
        ttl = ttl or self.default_ttl
        
        # Remove old entry if exists
        if key in self._cache:
            del self._cache[key]
        
        self._cache[key] = value
        self._expires[key] = time.time() + ttl
        self._stats["sets"] += 1
        
        # Enforce size limit
        self._enforce_size_limit()
    
    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        if key in self._cache:
            del self._cache[key]
            del self._expires[key]
            return True
        return False
    
    def clear(self):
        """Clear all cache entries."""
        self._cache.clear()
        self._expires.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        self._evict_expired()
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0
        
        return {
            "type": "L1_memory",
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate_percent": round(hit_rate, 2),
            "evictions": self._stats["evictions"],
            "sets": self._stats["sets"]
        }


# Global L1 cache instance
_l1_cache = L1Cache()


# ============================================================================
# L2: REDIS CACHE (Shared Across Instances)
# ============================================================================

class L2Cache:
    """
    Redis-backed cache for sharing across service instances.
    Provides distributed caching with JSON serialization.
    """
    
    def __init__(self, default_ttl: int = L2_DEFAULT_TTL, prefix: str = "cache:"):
        self.default_ttl = default_ttl
        self.prefix = prefix
        self._redis = None
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "errors": 0
        }
    
    def _get_redis(self):
        """Lazy load Redis connection."""
        if self._redis is None:
            try:
                import redis
                self._redis = redis.from_url(REDIS_URL, decode_responses=True)
            except Exception as e:
                print(f"⚠️ L2 Cache Redis connection failed: {e}")
                return None
        return self._redis
    
    def _make_key(self, key: str) -> str:
        return f"{self.prefix}{key}"
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from Redis cache."""
        r = self._get_redis()
        if not r:
            return None
        
        try:
            value = r.get(self._make_key(key))
            if value is None:
                self._stats["misses"] += 1
                return None
            
            self._stats["hits"] += 1
            return json.loads(value)
        except Exception as e:
            self._stats["errors"] += 1
            print(f"⚠️ L2 Cache get error: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: int = None):
        """Set value in Redis cache with TTL."""
        r = self._get_redis()
        if not r:
            return False
        
        ttl = ttl or self.default_ttl
        
        try:
            serialized = json.dumps(value)
            r.setex(self._make_key(key), ttl, serialized)
            self._stats["sets"] += 1
            return True
        except Exception as e:
            self._stats["errors"] += 1
            print(f"⚠️ L2 Cache set error: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete key from Redis cache."""
        r = self._get_redis()
        if not r:
            return False
        
        try:
            return r.delete(self._make_key(key)) > 0
        except Exception:
            return False
    
    def invalidate_pattern(self, pattern: str) -> int:
        """Delete all keys matching a pattern."""
        r = self._get_redis()
        if not r:
            return 0
        
        try:
            keys = r.keys(self._make_key(pattern))
            if keys:
                return r.delete(*keys)
            return 0
        except Exception as e:
            print(f"⚠️ L2 Cache pattern invalidation error: {e}")
            return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0
        
        stats = {
            "type": "L2_redis",
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate_percent": round(hit_rate, 2),
            "sets": self._stats["sets"],
            "errors": self._stats["errors"]
        }
        
        # Add Redis info if available
        r = self._get_redis()
        if r:
            try:
                info = r.info("memory")
                stats["redis_memory_mb"] = round(info.get("used_memory", 0) / 1024 / 1024, 2)
            except:
                pass
        
        return stats


# Global L2 cache instance
_l2_cache = L2Cache()


# ============================================================================
# MULTI-LAYER CACHE FACADE
# ============================================================================

class MultiLayerCache:
    """
    Unified interface for L1 + L2 caching.
    Implements read-through and write-through patterns.
    """
    
    def __init__(self, l1: L1Cache = None, l2: L2Cache = None):
        self.l1 = l1 or _l1_cache
        self.l2 = l2 or _l2_cache
    
    def get(self, key: str, use_l2: bool = True) -> Optional[Any]:
        """
        Get value, checking L1 first, then L2.
        Promotes L2 hits to L1 for faster subsequent access.
        """
        # Try L1 first
        value = self.l1.get(key)
        if value is not None:
            return value
        
        # Try L2 if enabled
        if use_l2:
            value = self.l2.get(key)
            if value is not None:
                # Promote to L1
                self.l1.set(key, value)
                return value
        
        return None
    
    def set(self, key: str, value: Any, l1_ttl: int = None, l2_ttl: int = None, use_l2: bool = True):
        """Set value in L1 and optionally L2."""
        self.l1.set(key, value, l1_ttl)
        if use_l2:
            self.l2.set(key, value, l2_ttl)
    
    def delete(self, key: str, use_l2: bool = True) -> bool:
        """Delete from both cache layers."""
        l1_result = self.l1.delete(key)
        l2_result = self.l2.delete(key) if use_l2 else False
        return l1_result or l2_result
    
    def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate L2 keys matching pattern and clear L1."""
        self.l1.clear()
        return self.l2.invalidate_pattern(pattern)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get combined cache statistics."""
        return {
            "l1": self.l1.get_stats(),
            "l2": self.l2.get_stats()
        }


# Global multi-layer cache instance
cache = MultiLayerCache()


# ============================================================================
# CACHE DECORATORS
# ============================================================================

def cached(key_prefix: str, ttl: int = 60, use_l2: bool = True):
    """
    Decorator to cache function results.
    
    Usage:
        @cached("guest", ttl=300)
        def get_guest(guest_id: str):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Build cache key from prefix + args
            key_parts = [key_prefix] + [str(a) for a in args]
            key_parts += [f"{k}={v}" for k, v in sorted(kwargs.items())]
            cache_key = hashlib.md5(":".join(key_parts).encode()).hexdigest()
            
            # Try cache first
            result = cache.get(cache_key, use_l2=use_l2)
            if result is not None:
                return result
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            if result is not None:
                cache.set(cache_key, result, l1_ttl=ttl, l2_ttl=ttl * 2, use_l2=use_l2)
            
            return result
        
        # Add cache invalidation method
        def invalidate(*args, **kwargs):
            key_parts = [key_prefix] + [str(a) for a in args]
            key_parts += [f"{k}={v}" for k, v in sorted(kwargs.items())]
            cache_key = hashlib.md5(":".join(key_parts).encode()).hexdigest()
            return cache.delete(cache_key, use_l2=use_l2)
        
        wrapper.invalidate = invalidate
        return wrapper
    
    return decorator


# ============================================================================
# CACHE WARMING
# ============================================================================

def warm_guest_cache(guest_ids: List[str], db) -> Dict[str, int]:
    """
    Pre-populate cache with frequently accessed guests.
    """
    from models import GuestModel
    
    warmed = 0
    for guest_id in guest_ids:
        guest = db.query(GuestModel).filter(GuestModel.id == guest_id).first()
        if guest:
            cache.set(
                f"guest:{guest_id}",
                {
                    "id": guest.id,
                    "name": guest.name,
                    "email": guest.email,
                    "language": guest.language
                },
                l1_ttl=300,
                l2_ttl=600
            )
            warmed += 1
    
    return {"guests_warmed": warmed, "total_requested": len(guest_ids)}
