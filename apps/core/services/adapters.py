"""
Channel Adapters for Lean MVP Architecture
==========================================

Merged from apps/gateway into Core service.
Handles webhook normalization for all messaging channels:
- WhatsApp (Twilio/Meta)
- LINE
- KakaoTalk (future)
- WeChat (future)

No external dependencies - runs in-process with Core.
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Literal, Any
from datetime import datetime
import uuid


# ============================================================================
# SHARED SCHEMAS (Inlined for zero latency)
# ============================================================================

class Guest(BaseModel):
    """Guest profile from messaging channel."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    channel_ids: Dict[str, str] = Field(default_factory=dict)
    language: str = "en"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MessageContent(BaseModel):
    """Normalized message content."""
    type: Literal["text", "image", "location", "template"]
    body: str
    media_url: Optional[str] = None
    metadata: Dict = Field(default_factory=dict)


class UnifiedMessage(BaseModel):
    """
    Standard message format for all channels.
    This is the canonical format used throughout the system.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    thread_id: Optional[str] = None
    channel: Literal["whatsapp", "line", "wechat", "kakao", "web"]
    direction: Literal["inbound", "outbound"]
    sender_id: str
    content: MessageContent
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    guest: Optional[Guest] = None


# ============================================================================
# WHATSAPP ADAPTER
# ============================================================================

class WhatsAppAdapter:
    """
    Adapter for WhatsApp webhooks (Twilio or Meta Graph API).
    Normalizes incoming webhooks to UnifiedMessage format.
    """
    
    @staticmethod
    def normalize(webhook_data: dict) -> UnifiedMessage:
        """
        Normalize WhatsApp webhook to UnifiedMessage.
        
        Handles both Twilio and Meta Graph API formats.
        """
        # Extract body from various possible locations
        body = (
            webhook_data.get("body") or 
            webhook_data.get("message", {}).get("text", {}).get("body") or 
            webhook_data.get("Body") or  # Twilio format
            str(webhook_data)
        )
        
        # Extract sender ID
        sender = (
            webhook_data.get("from") or 
            webhook_data.get("sender_id") or
            webhook_data.get("From") or  # Twilio format
            webhook_data.get("WaId") or  # Twilio WhatsApp ID
            "unknown"
        )
        
        # Clean phone number format
        if sender.startswith("whatsapp:"):
            sender = sender.replace("whatsapp:", "")
        
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
    
    @staticmethod
    def format_outbound(message: str, to: str, **kwargs) -> dict:
        """Format outbound message for WhatsApp API."""
        return {
            "to": to if to.startswith("whatsapp:") else f"whatsapp:{to}",
            "body": message,
            **kwargs
        }


# ============================================================================
# LINE ADAPTER
# ============================================================================

class LineAdapter:
    """
    Adapter for LINE Messaging API webhooks.
    Reference: https://developers.line.biz/en/docs/messaging-api/
    """
    
    @staticmethod
    def normalize(webhook_data: dict) -> UnifiedMessage:
        """
        Normalize LINE webhook to UnifiedMessage.
        
        LINE sends webhook events in the format:
        {
            "events": [
                {
                    "type": "message",
                    "message": {"type": "text", "text": "..."},
                    "source": {"userId": "..."}
                }
            ]
        }
        """
        events = webhook_data.get("events", [])
        if not events:
            raise ValueError("No events in LINE webhook payload")
        
        event = events[0]  # Process first event
        event_type = event.get("type")
        
        if event_type != "message":
            raise ValueError(f"Unsupported LINE event type: {event_type}")
        
        message = event.get("message", {})
        source = event.get("source", {})
        
        # Extract sender ID
        sender_id = (
            source.get("userId") or 
            source.get("groupId") or 
            source.get("roomId") or 
            "unknown"
        )
        
        # Determine content type and body
        msg_type = message.get("type", "text")
        
        if msg_type == "text":
            body = message.get("text", "")
            content_type = "text"
        elif msg_type == "image":
            body = "[Image]"
            content_type = "image"
        elif msg_type == "location":
            title = message.get("title", "Location")
            address = message.get("address", "")
            body = f"📍 {title}: {address}"
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
    
    @staticmethod
    def format_outbound(message: str, to: str, reply_token: str = None, **kwargs) -> dict:
        """Format outbound message for LINE API."""
        if reply_token:
            return {
                "replyToken": reply_token,
                "messages": [{"type": "text", "text": message}]
            }
        return {
            "to": to,
            "messages": [{"type": "text", "text": message}]
        }


# ============================================================================
# WEB ADAPTER (Direct browser messages)
# ============================================================================

class WebAdapter:
    """
    Adapter for direct web-based messaging.
    Used for browser-based chat widgets.
    """
    
    @staticmethod
    def normalize(webhook_data: dict) -> UnifiedMessage:
        """Normalize web chat message to UnifiedMessage."""
        body = webhook_data.get("message", "")
        sender = webhook_data.get("sender_id", webhook_data.get("session_id", "web_user"))
        guest_name = webhook_data.get("guest_name", "Web Guest")
        
        content = MessageContent(
            type="text",
            body=body,
            metadata=webhook_data
        )
        
        guest = Guest(
            name=guest_name,
            channel_ids={"web": sender}
        )
        
        return UnifiedMessage(
            channel="web",
            direction="inbound",
            sender_id=sender,
            content=content,
            guest=guest
        )


# ============================================================================
# ADAPTER REGISTRY
# ============================================================================

ADAPTERS = {
    "whatsapp": WhatsAppAdapter,
    "line": LineAdapter,
    "web": WebAdapter,
}


def get_adapter(channel: str):
    """Get adapter for a specific channel."""
    adapter = ADAPTERS.get(channel)
    if not adapter:
        raise ValueError(f"No adapter for channel: {channel}")
    return adapter


def normalize_message(channel: str, webhook_data: dict) -> UnifiedMessage:
    """
    Normalize a webhook payload to UnifiedMessage.
    
    Args:
        channel: Channel name (whatsapp, line, web)
        webhook_data: Raw webhook payload
    
    Returns:
        Normalized UnifiedMessage
    """
    adapter = get_adapter(channel)
    return adapter.normalize(webhook_data)
