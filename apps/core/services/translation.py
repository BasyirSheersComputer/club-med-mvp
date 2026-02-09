"""
Multi-Provider Translation Service with Fallback and Usage Tracking.
Primary: Google Gemini (gemini-2.0-flash)
Fallback: OpenAI (gpt-4o-mini)

Designed for Club Med's multilingual guest communication.
"""
import os
import json
from typing import Optional, Tuple, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
import threading

# ============================================================================
# CONFIGURATION
# ============================================================================

class AIProvider(Enum):
    GEMINI = "gemini"
    OPENAI = "openai"
    NONE = "none"

@dataclass
class ProviderConfig:
    name: str
    api_key: Optional[str]
    model: str
    is_available: bool = True
    consecutive_failures: int = 0
    max_failures_before_disable: int = 3
    disabled_until: Optional[datetime] = None

# API Keys from environment
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Provider configurations
PROVIDERS: Dict[AIProvider, ProviderConfig] = {
    AIProvider.GEMINI: ProviderConfig(
        name="Google Gemini",
        api_key=GEMINI_API_KEY,
        model="gemini-2.0-flash"
    ),
    AIProvider.OPENAI: ProviderConfig(
        name="OpenAI",
        api_key=OPENAI_API_KEY,
        model="gpt-4o-mini"
    )
}

# Supported languages for Club Med resorts
SUPPORTED_LANGUAGES = {
    "en": "English",
    "ja": "Japanese", 
    "zh": "Chinese (Simplified)",
    "fr": "French",
    "ko": "Korean",
    "th": "Thai",
    "id": "Indonesian",
    "vi": "Vietnamese"
}

# ============================================================================
# USAGE TRACKING
# ============================================================================

@dataclass
class UsageRecord:
    provider: str
    operation: str  # "detect_language", "translate"
    input_tokens: int
    output_tokens: int
    cost_estimate: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    success: bool = True
    error_message: Optional[str] = None

class UsageTracker:
    """Thread-safe usage tracking for AI API calls."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._records: list[UsageRecord] = []
        self._totals: Dict[str, Dict[str, Any]] = {
            "gemini": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "errors": 0},
            "openai": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "errors": 0}
        }
    
    def record(self, record: UsageRecord):
        with self._lock:
            self._records.append(record)
            provider = record.provider
            if provider in self._totals:
                self._totals[provider]["calls"] += 1
                self._totals[provider]["input_tokens"] += record.input_tokens
                self._totals[provider]["output_tokens"] += record.output_tokens
                self._totals[provider]["cost"] += record.cost_estimate
                if not record.success:
                    self._totals[provider]["errors"] += 1
    
    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "totals": dict(self._totals),
                "recent_records": [
                    {
                        "provider": r.provider,
                        "operation": r.operation,
                        "tokens": r.input_tokens + r.output_tokens,
                        "cost": r.cost_estimate,
                        "success": r.success,
                        "timestamp": r.timestamp.isoformat()
                    }
                    for r in self._records[-10:]  # Last 10 records
                ]
            }
    
    def get_provider_status(self) -> Dict[str, Any]:
        """Get current status of all providers."""
        status = {}
        for provider, config in PROVIDERS.items():
            status[provider.value] = {
                "name": config.name,
                "available": config.api_key is not None and config.is_available,
                "consecutive_failures": config.consecutive_failures,
                "model": config.model
            }
        return status

# Global usage tracker instance
usage_tracker = UsageTracker()

# ============================================================================
# PROVIDER CLIENTS
# ============================================================================

# Initialize Gemini
gemini_model = None
if GEMINI_API_KEY:
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel("gemini-2.0-flash")
        print("✅ Gemini API initialized")
    except Exception as e:
        print(f"❌ Gemini initialization failed: {e}")

# Initialize OpenAI
openai_client = None
if OPENAI_API_KEY:
    try:
        from openai import OpenAI
        openai_client = OpenAI(api_key=OPENAI_API_KEY)
        print("✅ OpenAI API initialized")
    except Exception as e:
        print(f"❌ OpenAI initialization failed: {e}")

# ============================================================================
# COST ESTIMATION (approximate)
# ============================================================================

def estimate_cost(provider: AIProvider, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost based on token usage (very approximate)."""
    if provider == AIProvider.GEMINI:
        # Gemini Flash is much cheaper
        return (input_tokens * 0.000000075) + (output_tokens * 0.0000003)
    elif provider == AIProvider.OPENAI:
        # GPT-4o-mini pricing
        return (input_tokens * 0.00000015) + (output_tokens * 0.0000006)
    return 0.0

# ============================================================================
# CORE TRANSLATION FUNCTIONS
# ============================================================================

def _call_gemini(prompt: str, system_prompt: str) -> Tuple[str, int, int]:
    """Call Gemini API and return (response, input_tokens, output_tokens)."""
    if not gemini_model:
        raise ValueError("Gemini not initialized")
    
    full_prompt = f"{system_prompt}\n\nUser: {prompt}"
    response = gemini_model.generate_content(full_prompt)
    
    # Approximate token count (Gemini doesn't always return token counts)
    input_tokens = len(full_prompt) // 4
    output_tokens = len(response.text) // 4
    
    return response.text.strip(), input_tokens, output_tokens


def _call_openai(prompt: str, system_prompt: str) -> Tuple[str, int, int]:
    """Call OpenAI API and return (response, input_tokens, output_tokens)."""
    if not openai_client:
        raise ValueError("OpenAI not initialized")
    
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=500
    )
    
    input_tokens = response.usage.prompt_tokens if response.usage else 0
    output_tokens = response.usage.completion_tokens if response.usage else 0
    
    return response.choices[0].message.content.strip(), input_tokens, output_tokens


def _call_with_fallback(prompt: str, system_prompt: str, operation: str) -> Tuple[str, AIProvider]:
    """
    Try Gemini first, fallback to OpenAI if it fails.
    Returns (response_text, provider_used).
    """
    # Try Gemini first
    gemini_config = PROVIDERS[AIProvider.GEMINI]
    if gemini_config.api_key and gemini_config.is_available:
        try:
            response, input_tokens, output_tokens = _call_gemini(prompt, system_prompt)
            
            # Record success
            gemini_config.consecutive_failures = 0
            usage_tracker.record(UsageRecord(
                provider="gemini",
                operation=operation,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_estimate=estimate_cost(AIProvider.GEMINI, input_tokens, output_tokens)
            ))
            
            print(f"🟢 Gemini: {operation} completed")
            return response, AIProvider.GEMINI
            
        except Exception as e:
            print(f"⚠️ Gemini failed: {e}")
            gemini_config.consecutive_failures += 1
            
            usage_tracker.record(UsageRecord(
                provider="gemini",
                operation=operation,
                input_tokens=0,
                output_tokens=0,
                cost_estimate=0.0,
                success=False,
                error_message=str(e)
            ))
            
            # Disable if too many failures
            if gemini_config.consecutive_failures >= gemini_config.max_failures_before_disable:
                gemini_config.is_available = False
                print(f"🔴 Gemini disabled after {gemini_config.consecutive_failures} failures")
    
    # Fallback to OpenAI
    openai_config = PROVIDERS[AIProvider.OPENAI]
    if openai_config.api_key and openai_config.is_available:
        try:
            response, input_tokens, output_tokens = _call_openai(prompt, system_prompt)
            
            openai_config.consecutive_failures = 0
            usage_tracker.record(UsageRecord(
                provider="openai",
                operation=operation,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_estimate=estimate_cost(AIProvider.OPENAI, input_tokens, output_tokens)
            ))
            
            print(f"🟡 OpenAI (fallback): {operation} completed")
            return response, AIProvider.OPENAI
            
        except Exception as e:
            print(f"❌ OpenAI also failed: {e}")
            openai_config.consecutive_failures += 1
            
            usage_tracker.record(UsageRecord(
                provider="openai",
                operation=operation,
                input_tokens=0,
                output_tokens=0,
                cost_estimate=0.0,
                success=False,
                error_message=str(e)
            ))
    
    # Both failed
    raise ValueError("All AI providers failed")


def reset_provider(provider: AIProvider):
    """Re-enable a disabled provider (called when issues are resolved)."""
    if provider in PROVIDERS:
        PROVIDERS[provider].is_available = True
        PROVIDERS[provider].consecutive_failures = 0
        print(f"✅ {PROVIDERS[provider].name} re-enabled")


# ============================================================================
# PUBLIC API
# ============================================================================

def detect_language(text: str) -> Tuple[str, float]:
    """
    Detect the language of input text.
    Returns: (language_code, confidence_score)
    """
    if not text.strip():
        return ("en", 0.0)
    
    system_prompt = """You are a language detection assistant. Analyze the input text and return ONLY a JSON object with:
- "language_code": ISO 639-1 code (e.g., "en", "ja", "zh", "fr")
- "confidence": float between 0 and 1
Do not include any other text, just the JSON."""
    
    try:
        response, provider = _call_with_fallback(text, system_prompt, "detect_language")
        result = json.loads(response)
        return (result.get("language_code", "en"), result.get("confidence", 0.5))
    except Exception as e:
        print(f"❌ Language detection failed: {e}")
        return ("en", 0.0)


def translate_text(text: str, source_lang: str, target_lang: str = "en") -> str:
    """
    Translate text from source language to target language.
    Default target is English (for agent dashboard).
    """
    if not text.strip() or source_lang == target_lang:
        return text
    
    source_name = SUPPORTED_LANGUAGES.get(source_lang, source_lang)
    target_name = SUPPORTED_LANGUAGES.get(target_lang, target_lang)
    
    system_prompt = f"""You are a professional translator for Club Med resort communications.
Translate the following text from {source_name} to {target_name}.
Maintain a friendly, hospitable tone appropriate for luxury resort guest services.
Return ONLY the translated text, no explanations."""
    
    try:
        response, provider = _call_with_fallback(text, system_prompt, "translate")
        print(f"🌐 Translated [{source_lang} → {target_lang}]: '{text[:30]}...' → '{response[:30]}...'")
        return response
    except Exception as e:
        print(f"❌ Translation failed: {e}")
        return text


def process_message_translation(message_body: str, guest_language: Optional[str] = None) -> dict:
    """
    Full translation pipeline for incoming messages.
    """
    if guest_language:
        detected_lang = guest_language
        confidence = 1.0
    else:
        detected_lang, confidence = detect_language(message_body)
        print(f"🔍 Detected language: {detected_lang} (confidence: {confidence:.2f})")
    
    translated_text = translate_text(message_body, detected_lang, "en")
    
    return {
        "original_text": message_body,
        "detected_language": detected_lang,
        "language_confidence": confidence,
        "translated_text": translated_text,
        "translation_target": "en"
    }


def translate_agent_reply(reply_text: str, target_lang: str) -> str:
    """Translate agent's English reply back to guest's language."""
    if target_lang == "en":
        return reply_text
    return translate_text(reply_text, "en", target_lang)


def get_usage_stats() -> Dict[str, Any]:
    """Get usage statistics for monitoring."""
    return {
        "provider_status": usage_tracker.get_provider_status(),
        "usage": usage_tracker.get_summary()
    }
