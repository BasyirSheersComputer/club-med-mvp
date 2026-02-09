from fastapi import FastAPI, HTTPException
import httpx
import os
import redis
from pydantic import BaseModel, Field
from typing import Optional, Dict, Literal
from datetime import datetime
import uuid

# --- Shared Schema Definitions (Inlined for safety) ---
class Guest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    channel_ids: Dict[str, str] = Field(default_factory=dict)
    language: str = "en"
    created_at: datetime = Field(default_factory=datetime.utcnow)

class MessageContent(BaseModel):
    type: Literal["text", "image", "location", "template"]
    body: str
    media_url: Optional[str] = None
    metadata: Dict = Field(default_factory=dict)

class UnifiedMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    thread_id: Optional[str] = None
    channel: Literal["whatsapp", "line", "wechat", "kakao", "web"]
    direction: Literal["inbound", "outbound"]
    sender_id: str
    content: MessageContent
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    guest: Optional[Guest] = None

# --- Adapter Logic ---
class WhatsAppAdapter:
    @staticmethod
    def normalize(webhook_data: dict) -> UnifiedMessage:
        body = webhook_data.get("body") or webhook_data.get("message", {}).get("text", {}).get("body") or str(webhook_data)
        sender = webhook_data.get("from") or webhook_data.get("sender_id") or "unknown"
        
        content = MessageContent(
            type="text",
            body=body,
            metadata=webhook_data
        )
        
        guest = Guest(
            name="Guest",
            channel_ids={"whatsapp": sender}
        )
        
        return UnifiedMessage(
            channel="whatsapp",
            direction="inbound",
            sender_id=sender,
            content=content,
            guest=guest
        )

# --- Application ---
app = FastAPI(title="ResortOS Gateway", version="0.1.0")

CORE_URL = os.getenv("CORE_SERVICE_URL", "http://core:8080")

@app.get("/")
def health_check():
    return {"status": "ok", "service": "gateway"}

@app.get("/health/upstream")
async def upstream_health_check():
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{CORE_URL}/")
            if resp.status_code == 200:
                return {"status": "ok", "upstream": "core_reachable", "details": resp.json()}
            else:
                raise HTTPException(status_code=503, detail="Core returned non-200")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Core unreachable: {str(e)}")

@app.post("/webhook/whatsapp")
async def receive_whatsapp(request: dict):
    try:
        # Normalize to UnifiedMessage
        unified_msg = WhatsAppAdapter.normalize(request)
        
        r = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"))
        # Verify connection
        r.ping()
        
        # Publish event as JSON string
        event_data = unified_msg.model_dump_json()
        r.publish("events", event_data)
        
        return {"status": "received", "id": unified_msg.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


# --- Line Adapter ---
class LineAdapter:
    """
    Adapter for LINE Messaging API webhooks.
    Normalizes LINE webhook events to UnifiedMessage format.
    Reference: https://developers.line.biz/en/docs/messaging-api/receiving-messages/
    """
    @staticmethod
    def normalize(webhook_data: dict) -> UnifiedMessage:
        # LINE sends events array
        events = webhook_data.get("events", [])
        if not events:
            raise ValueError("No events in LINE webhook payload")
        
        event = events[0]  # Process first event (batch handling can be added later)
        event_type = event.get("type")
        
        if event_type != "message":
            raise ValueError(f"Unsupported LINE event type: {event_type}")
        
        message = event.get("message", {})
        source = event.get("source", {})
        
        # Extract sender ID (userId for 1:1 chats, groupId/roomId for group chats)
        sender_id = source.get("userId") or source.get("groupId") or source.get("roomId") or "unknown"
        
        # Determine content type and body
        msg_type = message.get("type", "text")
        if msg_type == "text":
            body = message.get("text", "")
            content_type = "text"
        elif msg_type == "image":
            body = "[Image]"
            content_type = "image"
        elif msg_type == "location":
            body = f"📍 {message.get('title', 'Location')}: {message.get('address', '')}"
            content_type = "location"
        else:
            body = f"[{msg_type}]"
            content_type = "text"
        
        content = MessageContent(
            type=content_type,
            body=body,
            metadata={
                "line_message_id": message.get("id"),
                "line_reply_token": event.get("replyToken"),
                "original_event": event
            }
        )
        
        guest = Guest(
            name="LINE Guest",
            channel_ids={"line": sender_id}
        )
        
        return UnifiedMessage(
            channel="line",
            direction="inbound",
            sender_id=sender_id,
            content=content,
            guest=guest
        )


@app.post("/webhook/line")
async def receive_line(request: dict):
    """
    LINE Messaging API webhook endpoint.
    Receives webhook events from LINE and normalizes them to UnifiedMessage.
    """
    try:
        # Normalize to UnifiedMessage
        unified_msg = LineAdapter.normalize(request)
        
        r = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"))
        r.ping()
        
        # Publish event as JSON string
        event_data = unified_msg.model_dump_json()
        r.publish("events", event_data)
        
        return {"status": "received", "id": unified_msg.id, "channel": "line"}
    except ValueError as e:
        # Non-message events (e.g., follow, unfollow) - acknowledge but don't process
        return {"status": "acknowledged", "note": str(e)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LINE processing failed: {str(e)}")

