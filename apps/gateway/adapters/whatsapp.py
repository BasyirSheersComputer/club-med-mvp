from packages.schemas import UnifiedMessage, MessageContent, Guest
import uuid

class WhatsAppAdapter:
    @staticmethod
    def normalize(webhook_data: dict) -> UnifiedMessage:
        # Simplified normalization for MVP
        # In a real scenario, this would parse Twilio/Meta payload structure
        
        # Extract content (fallback to raw if simple structure)
        body = webhook_data.get("body") or webhook_data.get("message", {}).get("text", {}).get("body") or str(webhook_data)
        sender = webhook_data.get("from") or webhook_data.get("sender_id") or "unknown"
        
        content = MessageContent(
            type="text",
            body=body,
            metadata=webhook_data
        )
        
        guest = Guest(
            name="Guest", # Placeholder, would look up or create based on phone
            channel_ids={"whatsapp": sender}
        )
        
        return UnifiedMessage(
            channel="whatsapp",
            direction="inbound",
            sender_id=sender,
            content=content,
            guest=guest
        )
