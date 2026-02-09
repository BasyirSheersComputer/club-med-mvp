import requests
import json

try:
    payload = {
        "from": "1234567890", 
        "body": "Hello Club Med!",
        "message": {"text": {"body": "Hello Club Med!"}}
    }
    resp = requests.post(
        "http://localhost:8000/webhook/whatsapp",
        json=payload,
        timeout=5
    )
    print(f"Status: {resp.status_code}")
    print(f"Body: {resp.json()}")
except Exception as e:
    print(f"Error: {e}")
