"""
Comprehensive test script for AI providers (Gemini + OpenAI fallback).
Tests language detection, translation, and usage monitoring.
"""
import httpx
import json

BASE_URL = "http://localhost:8000"
CORE_URL = "http://localhost:8001"

# Test 1: Line webhook with Japanese message
print("=" * 60)
print("TEST 1: LINE Webhook - Japanese Message")
print("=" * 60)
line_payload = {
    "destination": "Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "events": [
        {
            "type": "message",
            "message": {
                "type": "text",
                "id": "test_12345",
                "text": "こんにちは！予約の確認をお願いします。"  # "Hello! Please confirm my reservation." in Japanese
            },
            "timestamp": 1640000000000,
            "source": {
                "type": "user",
                "userId": "U_test_user_japanese"
            },
            "replyToken": "reply-token-test"
        }
    ]
}

response = httpx.post(f"{BASE_URL}/webhook/line", json=line_payload, timeout=30)
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
print()

# Test 2: WhatsApp webhook with Chinese message
print("=" * 60)
print("TEST 2: WhatsApp Webhook - Chinese Message")
print("=" * 60)
whatsapp_payload = {
    "from": "86123456789",
    "body": "你好，我想预订明天的晚餐。"  # "Hello, I want to book dinner for tomorrow." in Chinese
}

response = httpx.post(f"{BASE_URL}/webhook/whatsapp", json=whatsapp_payload, timeout=30)
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
print()

# Test 3: WhatsApp webhook with French message
print("=" * 60)
print("TEST 3: WhatsApp Webhook - French Message")
print("=" * 60)
french_payload = {
    "from": "33123456789",
    "body": "Bonjour! Je voudrais réserver une chambre pour deux personnes."  # "Hello! I would like to book a room for two people." in French
}

response = httpx.post(f"{BASE_URL}/webhook/whatsapp", json=french_payload, timeout=30)
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
print()

# Test 4: Check AI Usage Statistics
print("=" * 60)
print("TEST 4: AI Usage Monitoring")
print("=" * 60)
response = httpx.get(f"{CORE_URL}/ai/usage", timeout=10)
print(f"Status: {response.status_code}")
print(f"Usage Stats:")
print(json.dumps(response.json(), indent=2))
print()

print("=" * 60)
print("All tests completed!")
print("=" * 60)
