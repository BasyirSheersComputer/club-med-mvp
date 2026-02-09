"""
SLA (Service Level Agreement) Monitoring Service
=================================================

Handles:
- Tracking response times for guest messages
- SLA status updates (green/yellow/red)
- Real-time alerts via Socket.io
- Background monitoring task
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

# ============================================================================
# CONFIGURATION
# ============================================================================

# SLA thresholds in minutes
SLA_GREEN_THRESHOLD = 2   # Under 2 minutes = green
SLA_YELLOW_THRESHOLD = 5  # 2-5 minutes = yellow  
SLA_RED_THRESHOLD = 5     # Over 5 minutes = red (SLA breach)

# Check interval for background task
SLA_CHECK_INTERVAL = 30  # seconds

# ============================================================================
# SLA CALCULATION
# ============================================================================

def calculate_sla_status(
    last_guest_message: Optional[datetime],
    last_agent_reply: Optional[datetime]
) -> Dict[str, Any]:
    """
    Calculate current SLA status for a thread.
    
    Returns:
    {
        "status": "green" | "yellow" | "red",
        "wait_time_minutes": float,
        "breached": bool,
        "time_to_breach": float (minutes, negative if breached)
    }
    """
    if not last_guest_message:
        return {
            "status": "green",
            "wait_time_minutes": 0,
            "breached": False,
            "time_to_breach": SLA_RED_THRESHOLD
        }
    
    # If agent replied after guest message, SLA is met
    if last_agent_reply and last_agent_reply > last_guest_message:
        return {
            "status": "green",
            "wait_time_minutes": 0,
            "breached": False,
            "time_to_breach": SLA_RED_THRESHOLD
        }
    
    # Calculate wait time
    now = datetime.utcnow()
    wait_time = (now - last_guest_message).total_seconds() / 60  # minutes
    
    # Determine status
    if wait_time < SLA_GREEN_THRESHOLD:
        status = "green"
    elif wait_time < SLA_YELLOW_THRESHOLD:
        status = "yellow"
    else:
        status = "red"
    
    breached = wait_time >= SLA_RED_THRESHOLD
    time_to_breach = SLA_RED_THRESHOLD - wait_time
    
    return {
        "status": status,
        "wait_time_minutes": round(wait_time, 2),
        "breached": breached,
        "time_to_breach": round(time_to_breach, 2)
    }


def update_thread_sla(thread, db) -> Dict[str, Any]:
    """
    Update a thread's SLA status in the database.
    """
    sla_info = calculate_sla_status(
        thread.last_guest_message,
        thread.last_agent_reply
    )
    
    thread.sla_status = sla_info["status"]
    thread.sla_breached = sla_info["breached"]
    db.commit()
    
    return sla_info


# ============================================================================
# SLA MONITORING
# ============================================================================

async def check_all_threads_sla(db, sio=None) -> List[Dict[str, Any]]:
    """
    Check SLA status for all active threads.
    Returns list of threads that need attention.
    """
    from models import ThreadModel
    
    alerts = []
    
    try:
        active_threads = db.query(ThreadModel).filter(
            ThreadModel.status == "active"
        ).all()
        
        for thread in active_threads:
            sla_info = calculate_sla_status(
                thread.last_guest_message,
                thread.last_agent_reply
            )
            
            # Update if status changed
            if thread.sla_status != sla_info["status"]:
                old_status = thread.sla_status
                thread.sla_status = sla_info["status"]
                thread.sla_breached = sla_info["breached"]
                db.commit()
                
                alert = {
                    "thread_id": thread.id,
                    "guest_id": thread.guest_id,
                    "old_status": old_status,
                    "new_status": sla_info["status"],
                    "wait_time_minutes": sla_info["wait_time_minutes"],
                    "breached": sla_info["breached"]
                }
                alerts.append(alert)
                
                # Push to Socket.io if available
                if sio and sla_info["status"] in ["yellow", "red"]:
                    await push_sla_alert(sio, alert)
        
        return alerts
        
    except Exception as e:
        print(f"❌ SLA check error: {e}")
        return []


async def push_sla_alert(sio, alert: Dict[str, Any]):
    """
    Push SLA alert to connected clients via Socket.io.
    """
    try:
        await sio.emit("sla_alert", {
            "type": "sla_status_change",
            "thread_id": alert["thread_id"],
            "status": alert["new_status"],
            "wait_time": alert["wait_time_minutes"],
            "breached": alert["breached"],
            "timestamp": datetime.utcnow().isoformat()
        })
        print(f"📢 SLA Alert pushed: Thread {alert['thread_id'][:8]}... -> {alert['new_status']}")
    except Exception as e:
        print(f"⚠️ SLA alert push failed: {e}")


# ============================================================================
# BACKGROUND MONITORING TASK
# ============================================================================

class SLAMonitor:
    """
    Background task that continuously monitors SLA status.
    """
    
    def __init__(self, db_session_factory, sio=None):
        self.db_session_factory = db_session_factory
        self.sio = sio
        self.running = False
    
    async def start(self):
        """Start the background monitoring task."""
        self.running = True
        print(f"🔔 SLA Monitor started (checking every {SLA_CHECK_INTERVAL}s)")
        
        while self.running:
            try:
                db = self.db_session_factory()
                try:
                    alerts = await check_all_threads_sla(db, self.sio)
                    if alerts:
                        print(f"⚠️ SLA Monitor: {len(alerts)} status changes detected")
                finally:
                    db.close()
            except Exception as e:
                print(f"❌ SLA Monitor error: {e}")
            
            await asyncio.sleep(SLA_CHECK_INTERVAL)
    
    def stop(self):
        """Stop the background monitoring task."""
        self.running = False
        print("🔔 SLA Monitor stopped")


# ============================================================================
# SLA STATISTICS
# ============================================================================

def get_sla_stats(db) -> Dict[str, Any]:
    """
    Get SLA statistics for dashboard.
    """
    from models import ThreadModel
    from sqlalchemy import func
    
    try:
        total = db.query(func.count(ThreadModel.id)).filter(
            ThreadModel.status == "active"
        ).scalar() or 0
        
        green = db.query(func.count(ThreadModel.id)).filter(
            ThreadModel.status == "active",
            ThreadModel.sla_status == "green"
        ).scalar() or 0
        
        yellow = db.query(func.count(ThreadModel.id)).filter(
            ThreadModel.status == "active",
            ThreadModel.sla_status == "yellow"
        ).scalar() or 0
        
        red = db.query(func.count(ThreadModel.id)).filter(
            ThreadModel.status == "active",
            ThreadModel.sla_status == "red"
        ).scalar() or 0
        
        breached = db.query(func.count(ThreadModel.id)).filter(
            ThreadModel.sla_breached == True
        ).scalar() or 0
        
        return {
            "active_threads": total,
            "by_status": {
                "green": green,
                "yellow": yellow,
                "red": red
            },
            "total_breached": breached,
            "compliance_rate": round((total - red) / total * 100, 1) if total > 0 else 100.0
        }
    except Exception as e:
        print(f"⚠️ SLA stats error: {e}")
        return {
            "active_threads": 0,
            "by_status": {"green": 0, "yellow": 0, "red": 0},
            "total_breached": 0,
            "compliance_rate": 100.0
        }
