from pydantic import BaseModel, Field
from typing import Optional, Dict, Literal
from datetime import datetime
import uuid

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
