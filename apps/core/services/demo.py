"""
Demo Mode Simulator for High-Stakes Presentations
==================================================

Provides realistic demo scenarios without requiring actual channel integrations.
All channels (WhatsApp, LINE, WeChat, Kakao, Web) simulated with realistic data.

Features:
- Pre-built guest personas with booking data
- Realistic conversation scenarios
- LTV and revenue metrics
- Instant demo reset
"""
import asyncio
import random
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
import json


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class Channel(str, Enum):
    WHATSAPP = "whatsapp"
    LINE = "line"
    WECHAT = "wechat"
    KAKAO = "kakao"
    WEB = "web"


class GuestTier(str, Enum):
    PLATINUM = "Platinum"
    GOLD = "Gold"
    SILVER = "Silver"
    MEMBER = "Member"


@dataclass
class Booking:
    """Guest booking information."""
    resort: str
    room_type: str
    check_in: str
    check_out: str
    pax: int
    total_value: float
    add_ons: List[str] = field(default_factory=list)
    confirmation_number: str = field(default_factory=lambda: f"CM{random.randint(100000, 999999)}")


@dataclass
class GuestPreferences:
    """Guest preferences and notes."""
    dietary: List[str] = field(default_factory=list)
    activities: List[str] = field(default_factory=list)
    room_preferences: List[str] = field(default_factory=list)
    communication_style: str = "friendly"
    special_occasions: List[str] = field(default_factory=list)


@dataclass
class GuestLTV:
    """Lifetime value calculation."""
    historical_spend: float
    total_visits: int
    avg_booking_value: float
    predicted_annual: float
    churn_risk: str = "low"  # low, medium, high


@dataclass
class DemoGuest:
    """Complete guest profile for demo."""
    id: str
    name: str
    email: str
    phone: str
    language: str
    nationality: str
    tier: GuestTier
    channels: List[Channel]
    preferred_channel: Channel
    current_booking: Optional[Booking]
    preferences: GuestPreferences
    ltv: GuestLTV
    interaction_count: int = 0
    avg_response_time_sec: float = 0
    last_interaction: Optional[str] = None
    notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['tier'] = self.tier.value
        result['channels'] = [c.value for c in self.channels]
        result['preferred_channel'] = self.preferred_channel.value
        return result


@dataclass
class DemoMessage:
    """Simulated message for demo."""
    id: str
    guest_id: str
    guest_name: str
    channel: Channel
    direction: str  # inbound, outbound
    content: str
    timestamp: str
    thread_id: str
    booking_value: float = 0
    sentiment: str = "neutral"  # positive, neutral, negative, urgent


# ============================================================================
# DEMO DATA: GUEST PERSONAS
# ============================================================================

DEMO_GUESTS: Dict[str, DemoGuest] = {
    "G-001": DemoGuest(
        id="G-001",
        name="田中 優希 (Tanaka Yuki)",
        email="yuki.tanaka@example.jp",
        phone="+81-90-1234-5678",
        language="ja",
        nationality="Japanese",
        tier=GuestTier.PLATINUM,
        channels=[Channel.LINE, Channel.WHATSAPP],
        preferred_channel=Channel.LINE,
        current_booking=Booking(
            resort="Club Med Bali",
            room_type="Deluxe Suite Ocean View",
            check_in="2026-02-15",
            check_out="2026-02-22",
            pax=2,
            total_value=15800,
            add_ons=["Spa Zen Package", "Romantic Dinner", "Private Excursion"]
        ),
        preferences=GuestPreferences(
            dietary=["pescatarian"],
            activities=["yoga", "snorkeling", "cooking class"],
            room_preferences=["high floor", "quiet", "ocean view"],
            communication_style="formal",
            special_occasions=["anniversary"]
        ),
        ltv=GuestLTV(
            historical_spend=67500,
            total_visits=5,
            avg_booking_value=13500,
            predicted_annual=27000,
            churn_risk="low"
        ),
        interaction_count=23,
        avg_response_time_sec=32,
        notes="VIP repeat guest. Always requests Sato-san as personal concierge."
    ),
    
    "G-002": DemoGuest(
        id="G-002",
        name="李伟 (Li Wei)",
        email="liwei@example.cn",
        phone="+86-138-0000-1234",
        language="zh",
        nationality="Chinese",
        tier=GuestTier.GOLD,
        channels=[Channel.WECHAT],
        preferred_channel=Channel.WECHAT,
        current_booking=Booking(
            resort="Club Med Sanya",
            room_type="Family Suite",
            check_in="2026-02-20",
            check_out="2026-02-27",
            pax=4,
            total_value=12500,
            add_ons=["Kids Club Premium", "Family Photo Package"]
        ),
        preferences=GuestPreferences(
            dietary=["halal-friendly"],
            activities=["kids activities", "beach", "shows"],
            room_preferences=["connecting rooms", "near kids club"],
            communication_style="casual",
            special_occasions=["chinese new year"]
        ),
        ltv=GuestLTV(
            historical_spend=38000,
            total_visits=3,
            avg_booking_value=12666,
            predicted_annual=25000,
            churn_risk="low"
        ),
        interaction_count=15,
        avg_response_time_sec=45,
        notes="Family traveler. Children ages 6 and 9."
    ),
    
    "G-003": DemoGuest(
        id="G-003",
        name="Sophie Laurent",
        email="sophie.laurent@example.fr",
        phone="+33-6-1234-5678",
        language="fr",
        nationality="French",
        tier=GuestTier.PLATINUM,
        channels=[Channel.WHATSAPP, Channel.WEB],
        preferred_channel=Channel.WHATSAPP,
        current_booking=Booking(
            resort="Club Med Maldives",
            room_type="Overwater Villa",
            check_in="2026-02-18",
            check_out="2026-02-25",
            pax=2,
            total_value=28500,
            add_ons=["Sunset Cruise", "Private Dining", "Diving Package"]
        ),
        preferences=GuestPreferences(
            dietary=["vegetarian", "gluten-free"],
            activities=["diving", "spa", "sunset viewing"],
            room_preferences=["overwater", "sunset facing"],
            communication_style="friendly",
            special_occasions=["honeymoon"]
        ),
        ltv=GuestLTV(
            historical_spend=95000,
            total_visits=7,
            avg_booking_value=13571,
            predicted_annual=30000,
            churn_risk="low"
        ),
        interaction_count=31,
        avg_response_time_sec=28,
        notes="Top-tier VIP. CEO of tech company. Prefers minimal interruption."
    ),
    
    "G-004": DemoGuest(
        id="G-004",
        name="김민준 (Kim Min-jun)",
        email="minjun.kim@example.kr",
        phone="+82-10-1234-5678",
        language="ko",
        nationality="Korean",
        tier=GuestTier.SILVER,
        channels=[Channel.KAKAO],
        preferred_channel=Channel.KAKAO,
        current_booking=Booking(
            resort="Club Med Hokkaido",
            room_type="Superior Room Mountain View",
            check_in="2026-02-22",
            check_out="2026-02-26",
            pax=2,
            total_value=6800,
            add_ons=["Ski Pass", "Onsen Access"]
        ),
        preferences=GuestPreferences(
            dietary=[],
            activities=["skiing", "onsen", "sake tasting"],
            room_preferences=["mountain view"],
            communication_style="casual",
            special_occasions=[]
        ),
        ltv=GuestLTV(
            historical_spend=13500,
            total_visits=2,
            avg_booking_value=6750,
            predicted_annual=14000,
            churn_risk="medium"
        ),
        interaction_count=8,
        avg_response_time_sec=67,
        notes="First-time winter sports guest. May need extra guidance."
    ),
    
    "G-005": DemoGuest(
        id="G-005",
        name="James Thompson",
        email="james.thompson@example.com",
        phone="+1-555-123-4567",
        language="en",
        nationality="American",
        tier=GuestTier.GOLD,
        channels=[Channel.WHATSAPP, Channel.WEB],
        preferred_channel=Channel.WHATSAPP,
        current_booking=Booking(
            resort="Club Med Cancun",
            room_type="Jade Suite",
            check_in="2026-03-01",
            check_out="2026-03-08",
            pax=5,
            total_value=18900,
            add_ons=["All-Day Excursion", "Teens Club", "Golf Package"]
        ),
        preferences=GuestPreferences(
            dietary=["dairy-free"],
            activities=["golf", "water sports", "nightlife"],
            room_preferences=["spacious", "near pool"],
            communication_style="professional",
            special_occasions=["spring break"]
        ),
        ltv=GuestLTV(
            historical_spend=42000,
            total_visits=3,
            avg_booking_value=14000,
            predicted_annual=20000,
            churn_risk="low"
        ),
        interaction_count=19,
        avg_response_time_sec=42,
        notes="Family with teenagers and elderly parent. Needs accessibility info."
    )
}


# ============================================================================
# DEMO SCENARIOS
# ============================================================================

DEMO_SCENARIOS = [
    {
        "id": "vip-upgrade",
        "name": "VIP Room Upgrade Request",
        "guest_id": "G-001",
        "messages": [
            {"role": "guest", "content": "こんにちは。私の予約についてお問い合わせです。スイートへのアップグレードは可能でしょうか？", "delay": 0},
            {"role": "system", "content": "[AI Translation: Hello. I have an inquiry about my reservation. Is it possible to upgrade to a suite?]", "delay": 1},
        ],
        "context": "Platinum guest requesting upgrade during anniversary trip",
        "booking_value": 15800,
        "urgency": "medium"
    },
    {
        "id": "kids-club",
        "name": "Kids Club Inquiry",
        "guest_id": "G-002",
        "messages": [
            {"role": "guest", "content": "你好，请问儿童俱乐部几点开门？我的孩子6岁和9岁。", "delay": 0},
            {"role": "system", "content": "[AI Translation: Hello, what time does the kids club open? My children are 6 and 9 years old.]", "delay": 1},
        ],
        "context": "Family traveler planning daily activities for children",
        "booking_value": 12500,
        "urgency": "low"
    },
    {
        "id": "honeymoon-special",
        "name": "Honeymoon Special Request",
        "guest_id": "G-003",
        "messages": [
            {"role": "guest", "content": "Bonjour! C'est notre lune de miel et nous aimerions organiser un dîner romantique sur la plage. Est-ce possible?", "delay": 0},
            {"role": "system", "content": "[AI Translation: Hello! It's our honeymoon and we would like to organize a romantic dinner on the beach. Is this possible?]", "delay": 1},
        ],
        "context": "High-value honeymoon couple requesting premium experience",
        "booking_value": 28500,
        "urgency": "medium"
    },
    {
        "id": "ski-beginner",
        "name": "Ski Lesson Booking",
        "guest_id": "G-004",
        "messages": [
            {"role": "guest", "content": "안녕하세요. 스키 강습 예약하고 싶어요. 초보자용 수업이 있나요?", "delay": 0},
            {"role": "system", "content": "[AI Translation: Hello. I want to book ski lessons. Do you have beginner classes?]", "delay": 1},
        ],
        "context": "First-time skier needing guidance",
        "booking_value": 6800,
        "urgency": "low"
    },
    {
        "id": "urgent-complaint",
        "name": "Urgent Service Issue",
        "guest_id": "G-005",
        "messages": [
            {"role": "guest", "content": "Hi, we've been waiting 45 minutes for room service. My father is diabetic and needs to eat. This is unacceptable!", "delay": 0},
        ],
        "context": "Urgent complaint from Gold tier guest with accessibility needs",
        "booking_value": 18900,
        "urgency": "high"
    },
    {
        "id": "spa-booking",
        "name": "Spa Package Inquiry",
        "guest_id": "G-003",
        "messages": [
            {"role": "guest", "content": "Can we book a couples massage for tomorrow morning? We'd like the Zen Retreat package.", "delay": 0},
        ],
        "context": "Upsell opportunity for premium spa services",
        "booking_value": 28500,
        "urgency": "low"
    },
    {
        "id": "checkin-early",
        "name": "Early Check-in Request",
        "guest_id": "G-002",
        "messages": [
            {"role": "guest", "content": "我们的航班提前到达，可以提前入住吗？大概下午1点到酒店。", "delay": 0},
            {"role": "system", "content": "[AI Translation: Our flight arrives early, can we check in early? We'll arrive at the hotel around 1 PM.]", "delay": 1},
        ],
        "context": "Family with young children requesting early accommodation",
        "booking_value": 12500,
        "urgency": "medium"
    }
]


# ============================================================================
# DEMO DATA: SOP KNOWLEDGE BASE
# ============================================================================

@dataclass
class SOP:
    """Standard Operating Procedure for demo."""
    id: str
    title: str
    category: str
    content: str
    tags: List[str]

DEMO_SOPS = [
    SOP(
        id="SOP-001",
        title="Check-in Process (Standard & VIP)",
        category="Front Desk",
        content="1. Greet guest with 'Bonjour' (Club Med signature).\n2. Verify passport and visa.\n3. For VIP (Gold/Platinum): Escort immediately to lounge for private check-in.\n4. Issue digital wristband (connects to room & payments).\n5. Explain resort map and key timings.",
        tags=["check-in", "vip", "front desk"]
    ),
    SOP(
        id="SOP-002",
        title="Room Upgrade Policy",
        category="Reservations",
        content="Complimentary upgrades for Gold/Platinum members subject to availability upon arrival. Paid upgrades available for standard members. Check 'Upsell Availability' dashboard before offering.",
        tags=["upgrade", "room", "policy"]
    ),
    SOP(
        id="SOP-003",
        title="Dietary Requirement Handling",
        category="F&B",
        content="1. Flag dietary restrictions in profile (Allergies in RED).\n2. Notify Executive Chef for severe allergies.\n3. Walk guest through buffet labeling system.\n4. For Halal/Kosher: Provide certified menu options.",
        tags=["food", "allergy", "dietary"]
    ),
    SOP(
        id="SOP-004",
        title="Kids Club Registration",
        category="Activities",
        content="Required for children 4-17. Need vaccination record for Baby Club (4-23 months). Register via App or at lobby desk. Welcome pack includes hat and schedule.",
        tags=["kids", "family", "activities"]
    ),
    SOP(
        id="SOP-005",
        title="Typhoon/Severe Weather Protocol",
        category="Safety",
        content="1. Activate 'Resort Safety Mode' in system.\n2. Send broadcast message to all guests via App/WhatsApp.\n3. Secure outdoor furniture.\n4. Direct guests to main building assembly points if necessary.",
        tags=["safety", "emergency", "weather"]
    ),
    SOP(
        id="SOP-006",
        title="Sustainability & Eco-Initiatives (Borneo)",
        category="General Info",
        content="Club Med Borneo is BREEAM certified. Initiatives: 100% renewable energy, zero single-use plastic, onsite organic farm, rainwater harvesting. Explain 'Bye Bye Plastic' program to guests.",
        tags=["sustainability", "eco", "borneo", "breeam"]
    )
]

# ============================================================================
# EXTENDED GUESTS (Add Borneo Persona)
# ============================================================================

DEMO_SCENARIOS.append({
    "id": "borneo-eco",
    "name": "Borneo Eco-Initiative Inquiry",
    "guest_id": "G-006", # New guest
    "messages": [
        {"role": "guest", "content": "Hi, we are excited for our trip! We chose Borneo specifically for the eco-credentials. Can you tell us more about the BREEAM certification and plastic policy?", "delay": 0},
    ],
    "context": "Eco-conscious traveler visiting the new Borneo resort",
    "booking_value": 8200,
    "urgency": "low"
})

# ============================================================================
# DEMO STATE MANAGEMENT
# ============================================================================

class DemoSimulator:
    """Manages demo state and simulates guest interactions."""
    
    def __init__(self):
        self.guests = DEMO_GUESTS.copy()
        
        # Add new Borneo guest
        self.guests["G-006"] = DemoGuest(
            id="G-006",
            name="Emma Green",
            email="emma.green@example.co.uk",
            phone="+44-7700-900000",
            language="en",
            nationality="British",
            tier=GuestTier.GOLD,
            channels=[Channel.WHATSAPP],
            preferred_channel=Channel.WHATSAPP,
            current_booking=Booking(
                resort="Club Med Borneo",
                room_type="Eco-Villa Forest View",
                check_in="2026-04-10",
                check_out="2026-04-17",
                pax=2,
                total_value=8200,
                add_ons=["Jungle Trek", "Organic Farm Tour"]
            ),
            preferences=GuestPreferences(
                dietary=["vegan"],
                activities=["hiking", "nature photography"],
                room_preferences=["quiet", "sustainable toiletries"],
                communication_style="friendly",
                special_occasions=[]
            ),
            ltv=GuestLTV(
                historical_spend=22000,
                total_visits=2,
                avg_booking_value=11000,
                predicted_annual=15000,
                churn_risk="low"
            ),
            interaction_count=3,
            avg_response_time_sec=15,
            notes="Very focused on sustainability. Mention BREEAM certification."
        )

        self.messages: List[DemoMessage] = []
        self.active_scenarios: Dict[str, Any] = {}
        # Updated stats for service focus
        self.stats = {
            "total_interactions": 0,
            "channels": {"whatsapp": 0, "line": 0, "wechat": 0, "kakao": 0, "web": 0},
            "avg_response_time": 0,
            "total_revenue_at_risk": 0,
            "sla_breaches": 0,
            "ai_suggestions_used": 0,
            "ai_suggestions_total": 0,
            "automation_rate": 70.1, # Fixed demo value for now based on G.M Copilot target
            "resolution_rate": 92.5
        }
        self.sops = DEMO_SOPS
        self._running = False
    
    def get_guests(self) -> List[Dict[str, Any]]:
        """Return all demo guests with full profiles."""
        return [g.to_dict() for g in self.guests.values()]
    
    def get_guest(self, guest_id: str) -> Optional[Dict[str, Any]]:
        """Get single guest profile."""
        guest = self.guests.get(guest_id)
        return guest.to_dict() if guest else None
    
    def get_sops(self) -> List[Dict[str, Any]]:
        """Return all SOPs."""
        return [asdict(sop) for sop in self.sops]

    def simulate_scenario(self, scenario_id: str) -> Dict[str, Any]:
        """Trigger a demo scenario and return the first message."""
        # Check standard scenarios + the appended one
        all_scenarios = DEMO_SCENARIOS
        
        scenario = next((s for s in all_scenarios if s["id"] == scenario_id), None)
        if not scenario:
            return {"error": f"Scenario not found: {scenario_id}"}
        
        guest = self.guests.get(scenario["guest_id"])
        if not guest:
            return {"error": f"Guest not found: {scenario['guest_id']}"}
        
        # Create message
        first_msg = scenario["messages"][0]
        thread_id = f"T-{uuid.uuid4().hex[:8]}"
        
        message = DemoMessage(
            id=f"M-{uuid.uuid4().hex[:8]}",
            guest_id=guest.id,
            guest_name=guest.name,
            channel=guest.preferred_channel,
            direction="inbound",
            content=first_msg["content"],
            timestamp=datetime.utcnow().isoformat() + "Z",
            thread_id=thread_id,
            booking_value=scenario["booking_value"],
            sentiment="urgent" if scenario["urgency"] == "high" else "neutral"
        )
        
        self.messages.append(message)
        self.stats["total_interactions"] += 1
        self.stats["channels"][guest.preferred_channel.value] += 1
        self.stats["total_revenue_at_risk"] += scenario["booking_value"]
        
        # Update guest interaction count
        guest.interaction_count += 1
        guest.last_interaction = message.timestamp
        
        return {
            "message": {
                "id": message.id,
                "channel": message.channel.value,
                "direction": message.direction,
                "sender_id": guest.phone,
                "content": {"type": "text", "body": message.content},
                "timestamp": message.timestamp,
                "thread_id": message.thread_id,
                "guest": {
                    "id": guest.id,
                    "name": guest.name,
                    "channel_ids": {guest.preferred_channel.value: guest.phone}
                },
                "sla_status": "red" if scenario["urgency"] == "high" else "yellow" if scenario["urgency"] == "medium" else "green"
            },
            "guest_profile": guest.to_dict(),
            "scenario": {
                "id": scenario["id"],
                "name": scenario["name"],
                "context": scenario["context"],
                "booking_value": scenario["booking_value"],
                "urgency": scenario["urgency"]
            }
        }
    
    def simulate_random(self) -> Dict[str, Any]:
        """Trigger a random demo scenario."""
        scenario = random.choice(DEMO_SCENARIOS) # This now includes the appended Borneo scenario
        return self.simulate_scenario(scenario["id"])
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Get comprehensive dashboard statistics."""
        total_ltv = sum(g.ltv.predicted_annual for g in self.guests.values())
        total_value = sum(
            g.current_booking.total_value 
            for g in self.guests.values() 
            if g.current_booking
        )
        
        return {
            "summary": {
                "total_guests": len(self.guests),
                "active_bookings": sum(1 for g in self.guests.values() if g.current_booking),
                "total_interactions": self.stats["total_interactions"],
                "total_guest_value": total_value, # Renamed from total_booking_value
                "total_loyalty_score": total_ltv, # Renamed from total_ltv
                "avg_response_time_sec": self.stats["avg_response_time"] or 42.5,
                "automation_rate": self.stats["automation_rate"],
                "resolution_rate": self.stats["resolution_rate"]
            },
            "channel_distribution": self.stats["channels"],
            "tier_breakdown": {
                "Platinum": sum(1 for g in self.guests.values() if g.tier == GuestTier.PLATINUM),
                "Gold": sum(1 for g in self.guests.values() if g.tier == GuestTier.GOLD),
                "Silver": sum(1 for g in self.guests.values() if g.tier == GuestTier.SILVER),
                "Member": sum(1 for g in self.guests.values() if g.tier == GuestTier.MEMBER)
            },
            "top_guests_by_loyalty": sorted( # Renamed from by_ltv
                [{"name": g.name, "score": g.ltv.predicted_annual, "tier": g.tier.value} 
                 for g in self.guests.values()],
                key=lambda x: x["score"],
                reverse=True
            )[:5],
            "sla_performance": {
                "on_time": 94.2,
                "at_risk": 4.1,
                "breached": 1.7
            },
            "ai_metrics": {
                "suggestions_generated": 127,
                "suggestions_used": 89,
                "adoption_rate": 70.1,
                "avg_confidence": 0.87,
                "languages_detected": ["en", "ja", "zh", "fr", "ko"]
            },
            "needs_attention_value": self.stats["total_revenue_at_risk"] # Renamed from revenue_at_risk
        }
    
    def get_scenarios(self) -> List[Dict[str, Any]]:
        """List all available demo scenarios."""
        # Ensure we return valid guest names even for new appended scenarios
        results = []
        for s in DEMO_SCENARIOS:
            guest = self.guests.get(s["guest_id"])
            results.append({
                "id": s["id"],
                "name": s["name"],
                "guest_id": s["guest_id"],
                "guest_name": guest.name if guest else "Unknown",
                "channel": guest.preferred_channel.value if guest else "unknown",
                "booking_value": s["booking_value"],
                "urgency": s["urgency"],
                "context": s["context"]
            })
        return results
    
    def reset(self):
        """Reset demo state to initial."""
        # reset needs to re-instantiate guests including G-006
        self.__init__()
        return {"status": "reset", "message": "Demo state cleared"}


# Global demo simulator instance
demo_simulator = DemoSimulator()
