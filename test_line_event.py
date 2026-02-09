"""
Test script for Line webhook endpoint.
Simulates a LINE Messaging API webhook payload.
"""
import httpx

# Sample LINE Messaging API webhook payload
# Reference: https://developers.line.biz/en/docs/messaging-api/receiving-messages/
line_payload = {
    "destination": "Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "events": [
        {
            "type": "message",
            "message": {
                "type": "text",
                "id": "12345678901234",
                "text": "こんにちは！Club Medに問い合わせです。"  # "Hello! This is an inquiry.to Club Med." in Japanese
            },
            "timestamp": 1640000000000,
            "source": {
                "type": "user",
                "userId": "U0123456789abcdef0123456789abcdef"
            },
            "replyToken": "reply-token-xxxx"
        }
    ]
}

if __name__ == "__main__":
    response = httpx.post("http://localhost:8000/webhook/line", json=line_payload)
    print(f"Status: {response.status_code}")
    print(f"Body: {response.json()}")
