import requests
import time
import sys
import threading

# Configure logging
LOG_FILE = "validation_report.txt"

def log(message):
    print(message)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")

# Initialize log file
with open(LOG_FILE, "w", encoding="utf-8") as f:
    f.write(f"ResortOS Verification Log - Started at {time.ctime()}\n")
    f.write("="*60 + "\n\n")

def check(name, url, expected_status=200):
    try:
        start = time.time()
        r = requests.get(url, timeout=5)
        duration = (time.time() - start) * 1000
        if r.status_code == expected_status:
            log(f"✅ {name}: OK ({duration:.0f}ms)")
            try:
                return True, r.json()
            except:
                return True, r.text[:100] # Return partial text if not JSON
        else:
            log(f"❌ {name}: Failed (Status {r.status_code})")
            return False, r.text
    except Exception as e:
        log(f"❌ {name}: Failed ({str(e)})")
        return False, str(e)

def load_test(url, requests_count=50):
    log(f"\n⚡ Starting Load Test on {url} ({requests_count} requests)...")
    errors = 0
    start = time.time()
    
    def hit():
        nonlocal errors
        try:
            r = requests.get(url, timeout=2)
            if r.status_code != 200:
                errors += 1
        except:
            errors += 1

    threads = []
    for _ in range(requests_count):
        t = threading.Thread(target=hit)
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
        
    duration = time.time() - start
    rps = requests_count / duration
    log(f"   Result: {rps:.2f} req/s, Errors: {errors}")
    return errors == 0

log("🔍 Starting Gold Standard Stress Test...\n")

# 1. Infrastructure Checks
web_ok, _ = check("Web Console (Next.js)", "http://localhost:3000/")
core_ok, _ = check("Service Core (FastAPI)", "http://localhost:8001/") # Root is health check
gateway_ok, _ = check("Gateway Service (FastAPI)", "http://localhost:8000/") # Root is health check

# 2. Deep Health Checks
log("\n🏥 Performing Deep Health Checks...")
core_deep_ok, core_data = check("Core -> DB/Redis Connection", "http://localhost:8001/health/deep")
gateway_upstream_ok, gateway_data = check("Gateway -> Core Connection", "http://localhost:8000/health/upstream")

# 3. Load Stability
log("\n🏋️ Verifying Load Stability...")
load_ok = True
if core_deep_ok:
    load_ok = load_test("http://localhost:8001/health/deep")

# Summary
if all([web_ok, core_ok, gateway_ok, core_deep_ok, gateway_upstream_ok, load_ok]):
    log("\n🏆 GOLD STANDARD PASSED: All Systems Nominal.")
    sys.exit(0)
else:
    log("\n🔥 VALIDATION FAILED: Check logs.")
    sys.exit(1)
