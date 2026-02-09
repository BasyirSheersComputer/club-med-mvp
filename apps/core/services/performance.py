"""
Performance Monitoring Service for Phase 4
==========================================

Implements performance budgets and monitoring:
- Response time targets (<200ms p95)
- Webhook processing budgets (<500ms)
- AI generation budgets (<2s)
- Budget violation tracking and alerting
"""
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from functools import wraps
from collections import defaultdict
import statistics

# ============================================================================
# PERFORMANCE BUDGETS
# ============================================================================

PERFORMANCE_BUDGETS = {
    "api_endpoint": {
        "target_p95_ms": 200,
        "target_p99_ms": 500,
        "alert_threshold_ms": 1000
    },
    "webhook_processing": {
        "target_p95_ms": 500,
        "target_p99_ms": 1000,
        "alert_threshold_ms": 2000
    },
    "ai_suggestion": {
        "target_p95_ms": 2000,
        "target_p99_ms": 3000,
        "alert_threshold_ms": 5000
    },
    "database_query": {
        "target_p95_ms": 50,
        "target_p99_ms": 100,
        "alert_threshold_ms": 500
    },
    "cache_operation": {
        "target_p95_ms": 5,
        "target_p99_ms": 10,
        "alert_threshold_ms": 50
    }
}


# ============================================================================
# TIMING COLLECTOR
# ============================================================================

class PerformanceCollector:
    """Collects and analyzes performance metrics."""
    
    def __init__(self, max_samples: int = 10000):
        self.max_samples = max_samples
        self.timings: Dict[str, List[float]] = defaultdict(list)
        self.violations: List[Dict] = []
        self.max_violations = 100
    
    def record(self, category: str, endpoint: str, duration_ms: float):
        """Record a timing sample."""
        key = f"{category}:{endpoint}"
        
        # Trim old samples
        if len(self.timings[key]) >= self.max_samples:
            self.timings[key] = self.timings[key][1000:]
        
        self.timings[key].append(duration_ms)
        
        # Check budget violation
        budget = PERFORMANCE_BUDGETS.get(category, {})
        if budget and duration_ms > budget.get("alert_threshold_ms", float("inf")):
            self._record_violation(category, endpoint, duration_ms, budget)
    
    def _record_violation(self, category: str, endpoint: str, duration_ms: float, budget: Dict):
        """Record a budget violation."""
        if len(self.violations) >= self.max_violations:
            self.violations.pop(0)
        
        self.violations.append({
            "timestamp": datetime.utcnow().isoformat(),
            "category": category,
            "endpoint": endpoint,
            "duration_ms": round(duration_ms, 2),
            "threshold_ms": budget.get("alert_threshold_ms"),
            "severity": "critical" if duration_ms > budget.get("alert_threshold_ms", 0) * 2 else "warning"
        })
    
    def get_stats(self, category: str = None, endpoint: str = None) -> Dict[str, Any]:
        """Get performance statistics."""
        if category and endpoint:
            key = f"{category}:{endpoint}"
            samples = self.timings.get(key, [])
            return self._calculate_stats(key, samples)
        
        # Return all stats
        all_stats = {}
        for key, samples in self.timings.items():
            all_stats[key] = self._calculate_stats(key, samples)
        
        return all_stats
    
    def _calculate_stats(self, key: str, samples: List[float]) -> Dict[str, Any]:
        """Calculate percentiles and stats for samples."""
        if not samples:
            return {"samples": 0}
        
        sorted_samples = sorted(samples)
        n = len(sorted_samples)
        
        return {
            "samples": n,
            "min_ms": round(sorted_samples[0], 2),
            "max_ms": round(sorted_samples[-1], 2),
            "avg_ms": round(statistics.mean(samples), 2),
            "p50_ms": round(sorted_samples[int(n * 0.5)], 2),
            "p95_ms": round(sorted_samples[int(n * 0.95)], 2),
            "p99_ms": round(sorted_samples[min(int(n * 0.99), n - 1)], 2)
        }
    
    def get_budget_status(self) -> Dict[str, Any]:
        """Check all performance budgets."""
        status = {}
        
        for category, budget in PERFORMANCE_BUDGETS.items():
            category_keys = [k for k in self.timings.keys() if k.startswith(f"{category}:")]
            
            if not category_keys:
                status[category] = {"status": "no_data", "budget": budget}
                continue
            
            # Aggregate all samples for this category
            all_samples = []
            for key in category_keys:
                all_samples.extend(self.timings[key])
            
            if not all_samples:
                status[category] = {"status": "no_data", "budget": budget}
                continue
            
            stats = self._calculate_stats(category, all_samples)
            
            # Check against budget
            p95_ok = stats["p95_ms"] <= budget["target_p95_ms"]
            p99_ok = stats["p99_ms"] <= budget["target_p99_ms"]
            
            status[category] = {
                "status": "ok" if (p95_ok and p99_ok) else "exceeded",
                "p95_within_budget": p95_ok,
                "p99_within_budget": p99_ok,
                "actual": stats,
                "budget": budget
            }
        
        return status
    
    def get_violations(self, limit: int = 50) -> List[Dict]:
        """Get recent budget violations."""
        return self.violations[-limit:]


# Global performance collector
_perf_collector = PerformanceCollector()


# ============================================================================
# PERFORMANCE DECORATORS
# ============================================================================

def measure(category: str):
    """
    Decorator to measure function performance.
    
    Usage:
        @measure("api_endpoint")
        def get_guest(guest_id: str):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration_ms = (time.time() - start) * 1000
                _perf_collector.record(category, func.__name__, duration_ms)
        
        return wrapper
    return decorator


def measure_async(category: str):
    """Async version of measure decorator."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration_ms = (time.time() - start) * 1000
                _perf_collector.record(category, func.__name__, duration_ms)
        
        return wrapper
    return decorator


# ============================================================================
# API FUNCTIONS
# ============================================================================

def record_timing(category: str, endpoint: str, duration_ms: float):
    """Record a timing measurement."""
    _perf_collector.record(category, endpoint, duration_ms)


def get_performance_stats() -> Dict[str, Any]:
    """Get all performance statistics."""
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "budgets": PERFORMANCE_BUDGETS,
        "budget_status": _perf_collector.get_budget_status(),
        "detailed_stats": _perf_collector.get_stats(),
        "recent_violations": _perf_collector.get_violations(limit=20)
    }


def get_budget_violations(limit: int = 50) -> List[Dict]:
    """Get recent budget violations."""
    return _perf_collector.get_violations(limit)


def clear_performance_data():
    """Clear all collected performance data."""
    global _perf_collector
    _perf_collector = PerformanceCollector()
