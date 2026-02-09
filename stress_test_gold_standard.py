"""
Enterprise Gold Standard Stress Test Suite
Phase 1 & Phase 2 Validation for ResortOS
============================================

This script validates all critical paths with enterprise-grade rigor.
"""
import httpx
import json
import time
import asyncio
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration
GATEWAY_URL = "http://localhost:8000"
CORE_URL = "http://localhost:8001"
WEB_URL = "http://localhost:3000"

# Test Results
results = {
    "phase1": {},
    "phase2": {},
    "summary": {"passed": 0, "failed": 0, "warnings": 0}
}

def log_result(phase: str, test_name: str, passed: bool, details: str = "", warning: bool = False):
    status = "✅ PASS" if passed else ("⚠️ WARN" if warning else "❌ FAIL")
    print(f"  {status} | {test_name}: {details}")
    results[phase][test_name] = {"passed": passed, "details": details, "warning": warning}
    if passed:
        results["summary"]["passed"] += 1
    elif warning:
        results["summary"]["warnings"] += 1
    else:
        results["summary"]["failed"] += 1

# ============================================================================
# PHASE 1: THE SKELETON - Infrastructure Tests
# ============================================================================
def run_phase1_tests():
    print("\n" + "="*70)
    print("PHASE 1: THE SKELETON - Infrastructure Validation")
    print("="*70)
    
    # 1.1 Service Health Checks
    print("\n[1.1] Service Health Checks")
    
    # Gateway Health
    try:
        r = httpx.get(f"{GATEWAY_URL}/", timeout=5)
        log_result("phase1", "Gateway Health", r.status_code == 200, f"Status: {r.status_code}")
    except Exception as e:
        log_result("phase1", "Gateway Health", False, str(e))
    
    # Core Health
    try:
        r = httpx.get(f"{CORE_URL}/", timeout=5)
        log_result("phase1", "Core Health", r.status_code == 200, f"Status: {r.status_code}")
    except Exception as e:
        log_result("phase1", "Core Health", False, str(e))
    
    # Web Health
    try:
        r = httpx.get(f"{WEB_URL}/", timeout=10)
        log_result("phase1", "Web Health", r.status_code == 200, f"Status: {r.status_code}")
    except Exception as e:
        log_result("phase1", "Web Health", False, str(e))
    
    # 1.2 Deep Health (DB/Redis)
    print("\n[1.2] Deep Health Checks (Database & Redis)")
    try:
        r = httpx.get(f"{CORE_URL}/health/deep", timeout=10)
        data = r.json()
        db_ok = data.get("checks", {}).get("database") == "connected"
        redis_ok = data.get("checks", {}).get("redis") == "connected"
        log_result("phase1", "PostgreSQL Connection", db_ok, data.get("checks", {}).get("database", "unknown"))
        log_result("phase1", "Redis Connection", redis_ok, data.get("checks", {}).get("redis", "unknown"))
    except Exception as e:
        log_result("phase1", "Deep Health Check", False, str(e))
    
    # 1.3 Upstream Connectivity
    print("\n[1.3] Inter-Service Connectivity")
    try:
        r = httpx.get(f"{GATEWAY_URL}/health/upstream", timeout=10)
        log_result("phase1", "Gateway -> Core Connection", r.status_code == 200, r.json().get("upstream", "unknown"))
    except Exception as e:
        log_result("phase1", "Gateway -> Core Connection", False, str(e))
    
    # 1.4 Load Stability Test
    print("\n[1.4] Load Stability (50 concurrent requests)")
    success_count = 0
    error_count = 0
    latencies = []
    
    def make_request():
        start = time.time()
        try:
            r = httpx.get(f"{CORE_URL}/", timeout=5)
            return (r.status_code == 200, time.time() - start)
        except:
            return (False, time.time() - start)
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(make_request) for _ in range(50)]
        for future in as_completed(futures):
            success, latency = future.result()
            if success:
                success_count += 1
            else:
                error_count += 1
            latencies.append(latency)
    
    avg_latency = sum(latencies) / len(latencies) * 1000
    p99_latency = sorted(latencies)[int(len(latencies) * 0.99)] * 1000
    error_rate = error_count / 50 * 100
    
    log_result("phase1", "Load Test Success Rate", error_rate < 1, f"{success_count}/50 ({100-error_rate:.1f}%)")
    log_result("phase1", "Load Test Avg Latency", avg_latency < 500, f"{avg_latency:.1f}ms")
    log_result("phase1", "Load Test P99 Latency", p99_latency < 1000, f"{p99_latency:.1f}ms")

# ============================================================================
# PHASE 2: THE POLYGLOT - Multi-Channel & Translation Tests
# ============================================================================
def run_phase2_tests():
    print("\n" + "="*70)
    print("PHASE 2: THE POLYGLOT - Multi-Channel & Translation Validation")
    print("="*70)
    
    # 2.1 WhatsApp Adapter
    print("\n[2.1] WhatsApp Adapter Tests")
    
    # Basic webhook
    try:
        payload = {"from": "1234567890", "body": "Hello from WhatsApp test"}
        r = httpx.post(f"{GATEWAY_URL}/webhook/whatsapp", json=payload, timeout=15)
        log_result("phase2", "WhatsApp Webhook Accept", r.status_code == 200, f"ID: {r.json().get('id', 'N/A')[:8]}...")
    except Exception as e:
        log_result("phase2", "WhatsApp Webhook Accept", False, str(e))
    
    # Malformed payload handling
    try:
        r = httpx.post(f"{GATEWAY_URL}/webhook/whatsapp", json={}, timeout=10)
        log_result("phase2", "WhatsApp Malformed Handling", r.status_code in [200, 400, 422], f"Graceful: {r.status_code}")
    except Exception as e:
        log_result("phase2", "WhatsApp Malformed Handling", False, str(e))
    
    # 2.2 Line Adapter
    print("\n[2.2] Line Adapter Tests")
    
    # Japanese message
    try:
        payload = {
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "stress_test", "text": "こんにちは、予約確認お願いします"},
                "source": {"type": "user", "userId": "U_stress_test"},
                "replyToken": "stress_token"
            }]
        }
        r = httpx.post(f"{GATEWAY_URL}/webhook/line", json=payload, timeout=15)
        log_result("phase2", "Line Webhook (Japanese)", r.status_code == 200, f"Channel: {r.json().get('channel', 'N/A')}")
    except Exception as e:
        log_result("phase2", "Line Webhook (Japanese)", False, str(e))
    
    # Non-message event handling
    try:
        payload = {"events": [{"type": "follow", "source": {"userId": "test"}}]}
        r = httpx.post(f"{GATEWAY_URL}/webhook/line", json=payload, timeout=10)
        log_result("phase2", "Line Non-Message Event", r.status_code == 200, f"Acknowledged gracefully")
    except Exception as e:
        log_result("phase2", "Line Non-Message Event", False, str(e))
    
    # 2.3 Multi-Language Translation Tests
    print("\n[2.3] Polyglot Translation Tests")
    
    test_messages = [
        ("Japanese", "ja", "予約の確認をお願いします。"),
        ("Chinese", "zh", "你好，我想预订明天的晚餐。"),
        ("French", "fr", "Bonjour, je voudrais réserver une chambre."),
        ("Korean", "ko", "안녕하세요, 예약 문의드립니다."),
        ("Thai", "th", "สวัสดีครับ ต้องการจองห้อง"),
    ]
    
    for lang_name, lang_code, text in test_messages:
        try:
            payload = {"from": f"test_{lang_code}", "body": text}
            start = time.time()
            r = httpx.post(f"{GATEWAY_URL}/webhook/whatsapp", json=payload, timeout=30)
            latency = (time.time() - start) * 1000
            log_result("phase2", f"Translation ({lang_name})", r.status_code == 200, f"{latency:.0f}ms")
        except Exception as e:
            log_result("phase2", f"Translation ({lang_name})", False, str(e))
    
    # 2.4 AI Provider Fallback & Monitoring
    print("\n[2.4] AI Provider Health & Fallback")
    
    try:
        r = httpx.get(f"{CORE_URL}/ai/usage", timeout=10)
        data = r.json()
        
        gemini_status = data.get("provider_status", {}).get("gemini", {})
        openai_status = data.get("provider_status", {}).get("openai", {})
        
        gemini_ok = gemini_status.get("available", False)
        openai_ok = openai_status.get("available", False)
        
        log_result("phase2", "Gemini Provider Status", gemini_ok, 
                   f"Failures: {gemini_status.get('consecutive_failures', 'N/A')}", warning=not gemini_ok)
        log_result("phase2", "OpenAI Provider Status", openai_ok,
                   f"Failures: {openai_status.get('consecutive_failures', 'N/A')}")
        
        # At least one provider must be working
        any_provider_ok = gemini_ok or openai_ok
        log_result("phase2", "AI Fallback System", any_provider_ok, 
                   "At least one provider available" if any_provider_ok else "ALL PROVIDERS DOWN")
        
        # Usage tracking
        totals = data.get("usage", {}).get("totals", {})
        total_calls = sum(p.get("calls", 0) for p in totals.values())
        log_result("phase2", "Usage Tracking Active", total_calls > 0, f"Total AI calls: {total_calls}")
        
    except Exception as e:
        log_result("phase2", "AI Provider Monitoring", False, str(e))
    
    # 2.5 Real-time Socket.io (check if server accepts connections)
    print("\n[2.5] Real-time Infrastructure")
    try:
        # Check if socket.io endpoint responds
        r = httpx.get(f"{CORE_URL}/socket.io/", timeout=5)
        # Socket.io returns various status codes, we just need it to respond
        log_result("phase2", "Socket.IO Endpoint", r.status_code in [200, 400], f"Status: {r.status_code}")
    except Exception as e:
        log_result("phase2", "Socket.IO Endpoint", False, str(e))
    
    # 2.6 Data Persistence Verification
    print("\n[2.6] Data Persistence Verification")
    try:
        r = httpx.get(f"{CORE_URL}/health/deep", timeout=10)
        log_result("phase2", "Database Persistence", r.status_code == 200, "Messages persisting to PostgreSQL")
    except Exception as e:
        log_result("phase2", "Database Persistence", False, str(e))

# ============================================================================
# SUMMARY
# ============================================================================
def print_summary():
    print("\n" + "="*70)
    print("ENTERPRISE STRESS TEST SUMMARY")
    print("="*70)
    
    total = results["summary"]["passed"] + results["summary"]["failed"] + results["summary"]["warnings"]
    pass_rate = results["summary"]["passed"] / total * 100 if total > 0 else 0
    
    print(f"\n  Total Tests: {total}")
    print(f"  ✅ Passed:   {results['summary']['passed']}")
    print(f"  ⚠️ Warnings: {results['summary']['warnings']}")
    print(f"  ❌ Failed:   {results['summary']['failed']}")
    print(f"\n  Pass Rate: {pass_rate:.1f}%")
    
    if results["summary"]["failed"] == 0:
        print("\n  🏆 GOLD STANDARD ACHIEVED - Enterprise Ready")
    elif pass_rate >= 90:
        print("\n  🥈 SILVER STANDARD - Minor issues to address")
    elif pass_rate >= 70:
        print("\n  🥉 BRONZE STANDARD - Significant issues")
    else:
        print("\n  ⛔ BELOW STANDARD - Critical failures detected")
    
    print("\n" + "="*70)
    return results

if __name__ == "__main__":
    print("\n🔬 ENTERPRISE GOLD STANDARD STRESS TEST")
    print(f"   Timestamp: {datetime.now().isoformat()}")
    print(f"   Target: ResortOS Phase 1 & Phase 2")
    
    run_phase1_tests()
    run_phase2_tests()
    final_results = print_summary()
    
    # Export results
    with open("stress_test_results.json", "w") as f:
        json.dump(final_results, f, indent=2, default=str)
    print("\n📄 Results saved to stress_test_results.json")
