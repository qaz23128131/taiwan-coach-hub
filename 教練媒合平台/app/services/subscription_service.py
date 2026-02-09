from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from .. import models
import json

def get_active_plan(db: Session, coach_id: int):
    # Check for active subscription
    now = datetime.utcnow()
    sub = db.query(models.CoachSubscription).filter(
        models.CoachSubscription.coach_id == coach_id,
        models.CoachSubscription.is_active == 1,
        models.CoachSubscription.end_at > now
    ).order_by(models.CoachSubscription.created_at.desc()).first()
    
    if sub:
        return sub.plan_id
    return "free"

def get_subscription_details(db: Session, coach_id: int):
    now = datetime.utcnow()
    sub = db.query(models.CoachSubscription).filter(
        models.CoachSubscription.coach_id == coach_id,
        models.CoachSubscription.is_active == 1,
        models.CoachSubscription.end_at > now
    ).order_by(models.CoachSubscription.created_at.desc()).first()
    
    if sub:
        plan_names = {"free": "基本", "pro": "進階", "elite": "菁英"}
        return {
            "plan_id": sub.plan_id,
            "name_zh": plan_names.get(sub.plan_id, "未知"),
            "end_at": sub.end_at
        }
    return {
        "plan_id": "free",
        "name_zh": "基本",
        "end_at": None
    }

def activate_plan(db: Session, coach_id: int, plan_id: str, days: int = 7, source: str = "demo"):
    now = datetime.utcnow()
    
    # 1. Deactivate old ones
    db.query(models.CoachSubscription).filter(
        models.CoachSubscription.coach_id == coach_id,
        models.CoachSubscription.is_active == 1
    ).update({"is_active": 0})
    
    # 2. Add new subscription
    new_sub = models.CoachSubscription(
        coach_id=coach_id,
        plan_id=plan_id,
        start_at=now,
        end_at=now + timedelta(days=days),
        is_active=1,
        source=source
    )
    db.add(new_sub)
    
    # 3. Update coach profile for quick access
    coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == coach_id).first()
    if coach:
        coach.subscription_level = plan_id
    
    # 4. Log event
    event = models.Event(
        event_type="plan_upgrade",
        coach_id=coach_id,
        meta_json=json.dumps({"plan_id": plan_id, "days": days})
    )
    db.add(event)
    
    db.commit()
    return new_sub

def log_event(db: Session, event_type: str, coach_id: int = None, user_id: int = None, meta: dict = None):
    # Prevent spam: Check for duplicate event in the last 10 minutes (Unique Impression)
    if user_id:
        ten_mins_ago = datetime.utcnow() - timedelta(minutes=10)
        exists = db.query(models.Event).filter(
            models.Event.event_type == event_type,
            models.Event.coach_id == coach_id,
            models.Event.user_id == user_id,
            models.Event.created_at >= ten_mins_ago
        ).first()
        if exists:
            return

    event = models.Event(
        event_type=event_type,
        coach_id=coach_id,
        user_id=user_id,
        meta_json=json.dumps(meta or {})
    )
    db.add(event)
    db.commit()
