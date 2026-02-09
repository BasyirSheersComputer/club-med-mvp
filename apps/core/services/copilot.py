"""
Copilot Service for Phase 3: Smart Reply Generation
====================================================

Handles:
- Context-aware reply suggestions using RAG
- SOP-grounded responses for accuracy
- Multi-provider AI integration (Gemini/OpenAI)
"""
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

# Knowledge service
from services.knowledge import search_knowledge, get_knowledge_stats

# Translation service (for AI calls)
from services.translation import _call_with_fallback, usage_tracker, UsageRecord, estimate_cost, AIProvider

# ============================================================================
# CONFIGURATION
# ============================================================================

# Number of knowledge chunks to retrieve for context
RAG_TOP_K = 5

# Maximum conversation history to include
MAX_HISTORY_MESSAGES = 10

# ============================================================================
# PROMPT TEMPLATES
# ============================================================================

SMART_REPLY_SYSTEM_PROMPT = """You are the AI Copilot for Club Med resort front desk staff. 
Your role is to help generate professional, friendly, and accurate responses to guest inquiries.

IMPORTANT GUIDELINES:
1. Use the provided SOP/knowledge context to ensure accuracy
2. Maintain Club Med's "Spirit of l'Esprit Libre" - warm, welcoming, playful yet professional
3. Be concise but complete - guests appreciate quick, helpful responses
4. If the SOPs don't cover a topic, say so rather than making up information
5. Always be culturally sensitive and respectful

KNOWLEDGE CONTEXT:
{knowledge_context}

CONVERSATION HISTORY:
{conversation_history}

Generate a suggested reply that the agent can use or modify. The reply should be:
- Appropriate for the channel ({channel})
- In {language} (the guest's preferred language)
- Ready to send with minimal editing

GUEST'S MESSAGE: {guest_message}

Provide your suggested reply:"""


SLA_URGENCY_PROMPT = """Based on the following unanswered guest message, rate the urgency (1-5) and explain briefly:

Message: {message}
Time waiting: {wait_time}
Channel: {channel}

Respond in JSON format: {"urgency": 1-5, "reason": "brief explanation"}"""


# ============================================================================
# RAG PIPELINE
# ============================================================================

def build_knowledge_context(query: str, top_k: int = RAG_TOP_K) -> str:
    """
    Retrieve relevant knowledge chunks and format as context.
    """
    results = search_knowledge(query, n_results=top_k)
    
    if not results:
        return "No relevant SOP information found for this query."
    
    context_parts = []
    for i, result in enumerate(results, 1):
        source = result.get("metadata", {}).get("document_title", "Unknown")
        page = result.get("metadata", {}).get("page", "?")
        content = result.get("content", "")
        
        context_parts.append(f"[Source: {source}, Page {page}]\n{content}")
    
    return "\n\n---\n\n".join(context_parts)


def build_conversation_context(messages: List[Dict[str, Any]], max_messages: int = MAX_HISTORY_MESSAGES) -> str:
    """
    Format recent conversation history for context.
    """
    if not messages:
        return "No previous conversation history."
    
    recent = messages[-max_messages:] if len(messages) > max_messages else messages
    
    formatted = []
    for msg in recent:
        direction = "Guest" if msg.get("direction") == "inbound" else "Agent"
        body = msg.get("body", "")[:200]  # Truncate long messages
        formatted.append(f"{direction}: {body}")
    
    return "\n".join(formatted)


def generate_smart_reply(
    guest_message: str,
    conversation_history: List[Dict[str, Any]] = None,
    channel: str = "whatsapp",
    language: str = "en",
    include_knowledge: bool = True
) -> Dict[str, Any]:
    """
    Generate a smart reply suggestion using RAG.
    
    Returns:
    {
        "suggestion": str,
        "confidence": float,
        "source_chunks": list,
        "provider_used": str
    }
    """
    # 1. Build knowledge context (RAG)
    if include_knowledge:
        knowledge_context = build_knowledge_context(guest_message)
        knowledge_stats = get_knowledge_stats()
    else:
        knowledge_context = "Knowledge base not queried for this request."
        knowledge_stats = {}
    
    # 2. Build conversation context
    conv_context = build_conversation_context(conversation_history or [])
    
    # 3. Construct prompt
    prompt = guest_message
    system_prompt = SMART_REPLY_SYSTEM_PROMPT.format(
        knowledge_context=knowledge_context,
        conversation_history=conv_context,
        channel=channel,
        language=language,
        guest_message=guest_message
    )
    
    # 4. Call AI (with fallback)
    try:
        reply, provider = _call_with_fallback(prompt, system_prompt, "copilot_suggest")
        
        # Extract source chunks used (for tracking)
        source_chunks = []
        if include_knowledge:
            results = search_knowledge(guest_message, n_results=RAG_TOP_K)
            source_chunks = [r.get("id") for r in results if r.get("id")]
        
        return {
            "suggestion": reply.strip(),
            "confidence": 0.85 if provider.value == "gemini" else 0.80,
            "source_chunks": source_chunks,
            "provider_used": provider.value,
            "knowledge_chunks_available": knowledge_stats.get("total_chunks", 0)
        }
        
    except Exception as e:
        print(f"❌ Smart reply generation failed: {e}")
        return {
            "suggestion": "",
            "confidence": 0.0,
            "source_chunks": [],
            "provider_used": "none",
            "error": str(e)
        }


def analyze_message_urgency(
    message: str,
    wait_time_minutes: int,
    channel: str = "whatsapp"
) -> Dict[str, Any]:
    """
    Analyze message urgency for SLA prioritization.
    """
    import json
    
    prompt = message
    system_prompt = SLA_URGENCY_PROMPT.format(
        message=message,
        wait_time=f"{wait_time_minutes} minutes",
        channel=channel
    )
    
    try:
        response, provider = _call_with_fallback(prompt, system_prompt, "sla_analysis")
        
        # Parse JSON response
        try:
            result = json.loads(response)
            return {
                "urgency": result.get("urgency", 3),
                "reason": result.get("reason", "Unable to determine"),
                "provider_used": provider.value
            }
        except json.JSONDecodeError:
            return {
                "urgency": 3,
                "reason": response[:100],
                "provider_used": provider.value
            }
            
    except Exception as e:
        return {
            "urgency": 3,
            "reason": f"Analysis failed: {e}",
            "provider_used": "none"
        }


# ============================================================================
# COPILOT FEEDBACK
# ============================================================================

def record_suggestion_feedback(
    suggestion_id: str,
    was_used: bool,
    rating: Optional[int] = None,
    db = None
) -> bool:
    """
    Record agent feedback on a suggestion for improving the system.
    """
    if not db:
        return False
    
    from models import CopilotSuggestion
    
    try:
        suggestion = db.query(CopilotSuggestion).filter(
            CopilotSuggestion.id == suggestion_id
        ).first()
        
        if suggestion:
            suggestion.was_used = was_used
            if rating is not None:
                suggestion.agent_rating = rating
            db.commit()
            return True
        return False
    except Exception as e:
        print(f"❌ Feedback recording failed: {e}")
        return False


def get_copilot_stats(db = None) -> Dict[str, Any]:
    """
    Get Copilot usage statistics.
    """
    stats = {
        "knowledge_base": get_knowledge_stats(),
        "suggestions": {
            "total": 0,
            "used": 0,
            "usage_rate": 0.0,
            "avg_rating": 0.0
        }
    }
    
    if db:
        from models import CopilotSuggestion
        from sqlalchemy import func
        
        try:
            total = db.query(func.count(CopilotSuggestion.id)).scalar() or 0
            used = db.query(func.count(CopilotSuggestion.id)).filter(
                CopilotSuggestion.was_used == True
            ).scalar() or 0
            avg_rating = db.query(func.avg(CopilotSuggestion.agent_rating)).filter(
                CopilotSuggestion.agent_rating.isnot(None)
            ).scalar() or 0.0
            
            stats["suggestions"]["total"] = total
            stats["suggestions"]["used"] = used
            stats["suggestions"]["usage_rate"] = used / total * 100 if total > 0 else 0.0
            stats["suggestions"]["avg_rating"] = round(float(avg_rating), 2)
        except Exception as e:
            print(f"⚠️ Stats query failed: {e}")
    
    return stats
