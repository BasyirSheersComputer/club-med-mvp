import requests
import json

try:
    resp = requests.post(
        "http://localhost:8000/webhook/whatsapp",
        json={"event": "start_test", "user": "guest_123"},
        timeout=5
    )
    print(f"Status: {resp.status_code}")
    print(f"Body: {resp.json()}")
except Exception as e:
    print(f"Error: {e}")
