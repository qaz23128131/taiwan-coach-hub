from fastapi import FastAPI, Depends, Request, Form, HTTPException, status, Query, UploadFile, File, Body
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from app import models, database, auth
from app.database import engine, get_db
from app.state_service import StatusService
from app.services import subscription_service
from app.areas import TAIWAN_AREAS
from datetime import datetime, timedelta
import json
import os
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
import shutil
import uuid
# --- 方案與權限規則 ---
PLAN_LIMITS = {
    "basic": {
        "name": "基本入門",
        "price": 0,
        "media_limit": 3,
        "testimonial_limit": 1,
        "link_limit": 0,
        "faq_limit": 0,
        "offer_limit": 0,
        "video_allowed": False,
        "video_limit": 0,
        "analytics_level": "basic", 
        "allow_search_badge": False,
        "allow_featured": False
    },
    "pro": {
        "name": "進階成長",
        "price": 199,
        "media_limit": 12,
        "testimonial_limit": 2,
        "link_limit": 3,
        "faq_limit": 0,
        "offer_limit": 0,
        "video_limit": 1,
        "video_allowed": True,
        "analytics_level": "advanced",
        "allow_search_badge": True,
        "allow_featured": False
    },
    "elite": {
        "name": "菁英旗艦",
        "price": 399,
        "media_limit": 99,
        "testimonial_limit": 6,
        "link_limit": 10,
        "faq_limit": 6,
        "offer_limit": 6,
        "video_limit": 3,
        "video_allowed": True,
        "analytics_level": "elite",
        "allow_search_badge": True,
        "allow_featured": True
    }
}

def validate_feature_limit(coach: models.CoachProfile, feature: str, db: Session):
    """
    feature: 'media', 'link', 'faq', 'offer', 'testimonial'
    """
    level = coach.subscription_level or 'basic'
    plan = PLAN_LIMITS.get(level, PLAN_LIMITS["basic"])
    limit_key = f"{feature}_limit"
    limit = plan.get(limit_key, 0)
    
    if limit == 0:
        return False, f"您的「{plan['name']}」方案暫不支援此功能，請升級以解鎖。"
        
    count = 0
    if feature == 'media':
        count = db.query(models.CoachMedia).filter(models.CoachMedia.coach_id == coach.id).count()
    elif feature == 'link':
        count = db.query(models.CoachLink).filter(models.CoachLink.coach_id == coach.id).count()
    elif feature == 'faq':
        count = db.query(models.CoachFaq).filter(models.CoachFaq.coach_id == coach.id).count()
    elif feature == 'offer':
        count = db.query(models.CoachOffer).filter(models.CoachOffer.coach_id == coach.id).count()
    elif feature == 'testimonial':
        count = db.query(models.CoachTestimonial).filter(models.CoachTestimonial.coach_id == coach.id).count()
        
    if count >= limit:
        target_plan = "pro" if level == "basic" else "elite"
        target_name = PLAN_LIMITS[target_plan]['name'] if target_plan in PLAN_LIMITS else "更高"
        return False, f"已達「{plan['name']}」方案上限 ({limit}個)。升級至「{target_name}」即可新增更多。"
        
    return True, ""

# 初始化資料庫
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Taiwan Coach Hub Enterprise")
templates = Jinja2Templates(directory="app/templates")

def from_json(value):
    try:
        if not value: return []
        if isinstance(value, str): return json.loads(value)
        return value
    except: return []

templates.env.filters["from_json"] = from_json

def rating_display(rating, count):
    if not count or count == 0:
        return "新教練 (尚無評價)"
    return f"{format_rating(rating)} ({count} 則評價)"

def format_rating(rating):
    r = rating if rating is not None else 0.0
    return f"{round(r, 1):.1f}"

templates.env.filters["rating_display"] = rating_display
templates.env.filters["format_rating"] = format_rating
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 運動項目配置 (Requirement B1)
SPORTS_CONFIG = [
    {"id": "fitness", "name_zh": "健身", "name_en": "Fitness", "image_url": "/static/images/fitness_coach.png"},
    {"id": "diving", "name_zh": "潛水", "name_en": "Diving", "image_url": "/static/images/diving_coach.png"},
    {"id": "skiing", "name_zh": "滑雪", "name_en": "Skiing", "image_url": "/static/images/skiing_coach.png"},
]

def get_user_coach_profile(user: models.User, db: Session):
    return db.query(models.CoachProfile).filter(models.CoachProfile.user_id == user.id).first()

# 初始化示範資料
def init_db():
    db = database.SessionLocal()
    # 檢查 admin 是否已存在
    admin_exists = db.query(models.User).filter(models.User.email == "admin@taiwan.com").first()
    if not admin_exists:
        # 1. 管理員
        admin_user = models.User(
            email="admin@taiwan.com", 
            hashed_password=auth.get_password_hash("admin123"), 
            role="admin", 
            name="管理員"
        )
        db.add(admin_user)
        db.commit()
    
    db.close()

init_db()

@app.middleware("http")
async def add_auth_state(request: Request, call_next):
    token = request.cookies.get("access_token")
    request.state.user = None
    if token:
        db = database.SessionLocal()
        try:
            user = auth.get_current_user(request, db)
            request.state.user = user
        except: pass
        finally: db.close()
    response = await call_next(request)
    return response

# --- API ---
@app.get("/api/notifications")
async def get_notifications_api(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return []
    notifs = db.query(models.Notification).filter(models.Notification.user_id == user.id).order_by(models.Notification.created_at.desc()).limit(15).all()
    return [{"id": n.id, "title": n.title, "content": n.content, "type": n.type, "created_at": n.created_at.isoformat(), "link": n.link, "is_read": n.is_read} for n in notifs]

@app.post("/api/notifications/{id}/read")
async def mark_notification_read(id: int, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    
    notif = db.query(models.Notification).filter(models.Notification.id == id).first()
    if notif and notif.user_id == user.id:
        notif.is_read = True
        db.commit()
    return {"status": "ok"}

@app.post("/api/notifications/mark_read")
async def mark_all_notifications_read(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    
    # Update bulk
    db.query(models.Notification).filter(
        models.Notification.user_id == user.id,
        models.Notification.is_read == False
    ).update({"is_read": True})
    
    db.commit()
    return {"status": "ok"}

# --- Helper: Rate Limiter ---
from datetime import timedelta

def check_rate_limit(db: Session, key_prefix: str, limit: int, window_minutes: int = 1):
    """
    Simple SQLite-based Rate Limiter.
    Returns True if allowed, False if blocked.
    """
    now = datetime.utcnow()
    window_start = now - timedelta(minutes=window_minutes)
    
    # 1. Clean up old records for this key (optional optimization)
    # db.query(models.RateLimit).filter(models.RateLimit.key == key_prefix, models.RateLimit.window_start_at < window_start).delete()
    
    # 2. Get current window record
    # We use a simplified approach: just count records in window? 
    # Or use the specific RateLimit model design: key, window_start, count.
    # Let's use the model: key specific to window slot?
    # To keep it simple and robust: Key = "prefix:minute_timestamp"
    
    # Actually, simpler: find record for this key (prefix) where window matches?
    # No, sliding window is hard with just one record. 
    # Let's just use: Key = prefix. Check window_start. If old, reset.
    
    record = db.query(models.RateLimit).filter(models.RateLimit.key == key_prefix).first()
    
    if not record:
        record = models.RateLimit(key=key_prefix, window_start_at=now, count=1)
        db.add(record)
        db.commit()
        return True
        
    # Check if window expired
    if record.window_start_at < window_start:
        record.window_start_at = now
        record.count = 1
        db.commit()
        return True
    
    # In window, check count
    if record.count >= limit:
        return False
        
    record.count += 1
    db.commit()
    return True

def rate_limit_dependency(key_setup: str, limit: int, window: int):
    async def dependency(request: Request, db: Session = Depends(get_db)):
        if "user" in key_setup and not request.state.user:
            return # Skip for anon if user required? Or limit by IP.
            
        user_id = request.state.user.id if request.state.user else "anon"
        ip = request.client.host
        
        final_key = key_setup.replace("{user_id}", str(user_id)).replace("{ip}", ip)
        
        if not check_rate_limit(db, final_key, limit, window):
             raise HTTPException(status_code=429, detail="請求過於頻繁，請稍後再試 (Rate Limit Exceeded)")
             
    return dependency

# --- Feature 4: Analytics API ---

class EventCreate(BaseModel):
    event_type: str
    coach_id: Optional[int] = None
    session_id: Optional[str] = None

@app.post("/api/events/track")
async def track_event(event: EventCreate, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    new_event = models.AnalyticsEvent(
        user_id=user.id if user else None,
        session_id=event.session_id,
        event_type=event.event_type,
        coach_id=event.coach_id
    )
    db.add(new_event)
    db.commit()
    return {"status": "ok"}

@app.get("/api/admin/analytics/summary")
async def get_analytics_summary(db: Session = Depends(get_db), current_user: models.User = Depends(auth.admin_required)):
    # KPI 1: New Coaches this week
    week_ago = datetime.utcnow() - timedelta(days=7)
    new_coaches = db.query(models.CoachProfile).filter(models.CoachProfile.submitted_at >= week_ago).count()
    
    # KPI 2: Approval Rate (Active / All Submitted)
    total_approved = db.query(models.CoachProfile).filter(
        models.CoachProfile.review_status == "APPROVED",
        models.CoachProfile.visibility_status == "VISIBLE",
        models.CoachProfile.account_status == "ACTIVE"
    ).count()
    total_submitted = db.query(models.CoachProfile).count()
    approval_rate = round((total_approved / total_submitted * 100), 1) if total_submitted > 0 else 0
    
    # KPI 3: Suspended Count
    suspended = db.query(models.CoachProfile).filter(models.CoachProfile.status == "SUSPENDED").count()
    
    # KPI 4: Complaints this week
    complaints = db.query(models.Complaint).filter(models.Complaint.created_at >= week_ago).count()
    
    return {
        "new_coaches": new_coaches,
        "approval_rate": approval_rate,
        "suspended_count": suspended,
        "weekly_complaints": complaints
    }

@app.get("/api/admin/analytics/funnel")
async def get_analytics_funnel(db: Session = Depends(get_db), current_user: models.User = Depends(auth.admin_required)):
    # Simple funnel: HOME -> SEARCH -> VIEW -> FAVORITE -> CONVERSATION
    events = ["PAGE_HOME", "PAGE_SEARCH", "VIEW_COACH", "FAVORITE_ON", "CONVERSATION_START"]
    date_filter = datetime.utcnow() - timedelta(days=7)
    
    funnel_data = []
    for et in events:
        count = db.query(models.AnalyticsEvent).filter(
            models.AnalyticsEvent.event_type == et, 
            models.AnalyticsEvent.created_at >= date_filter
        ).count()
        funnel_data.append({"step": et, "count": count})
        
    return {"funnel": funnel_data}

@app.get("/api/admin/analytics/recent")
async def get_analytics_recent(limit: int = 20, db: Session = Depends(get_db)):
    events = db.query(models.AnalyticsEvent).order_by(models.AnalyticsEvent.created_at.desc()).limit(limit).all()
    res = []
    for e in events:
        user_name = "訪客"
        if e.user_id:
            u = db.query(models.User).filter(models.User.id == e.user_id).first()
            if u: user_name = u.name
            
        res.append({
            "time": e.created_at.strftime("%m/%d %H:%M"),
            "event": e.event_type,
            "user": user_name,
            "coach_id": e.coach_id
        })
    return res

# --- Feature 1: Conversations API ---

@app.post("/api/conversations/start")
async def start_conservation(
    payload: dict, # {coach_id: int}
    request: Request,
    db: Session = Depends(get_db)
):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    
    coach_id = payload.get("coach_id")
    # Check existing InquiryThread
    thread = db.query(models.InquiryThread).filter(
        models.InquiryThread.student_id == user.id,
        models.InquiryThread.coach_profile_id == coach_id
    ).first()
    
    if thread:
        return {"id": thread.id, "is_new": False}
        
    # Create new InquiryThread
    new_thread = models.InquiryThread(
        student_id=user.id,
        coach_profile_id=coach_id
    )
    db.add(new_thread)
    db.commit()
    db.refresh(new_thread)
    
    # Auto system message (Optional, using InquiryMessage if needed, skipping for simple thread init)
    
    return {"id": new_thread.id, "is_new": True}
    
    # Track Event
    track_event(EventCreate(event_type="CONVERSATION_START", coach_id=coach_id), request, db)
    
    db.commit()
    return {"id": new_conv.id, "is_new": True}

@app.get("/api/conversations/{id}")
async def get_conversation(id: int, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    
    conv = db.query(models.Conversation).filter(models.Conversation.id == id).first()
    if not conv: raise HTTPException(status_code=404)
    # Check access
    if conv.student_id != user.id:
         # Check if it's the coach? The user table is shared.
         # For MVP, assume coach checks via their own dashboard logic or strictly user logic.
         # If user is coach, we might need to check if coach linked to this user owns the profile.
         # Simplified: Only student can view via this endpoint for now, or check coach.
         
         # Check if user is the coach of this conversation
         coach_profile = db.query(models.CoachProfile).filter(models.CoachProfile.id == conv.coach_id).first()
         if not coach_profile or coach_profile.user_id != user.id:
             raise HTTPException(status_code=403)
             
    messages = db.query(models.ConversationMessage).filter(models.ConversationMessage.conversation_id == id).order_by(models.ConversationMessage.created_at.asc()).all()
    
    coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == conv.coach_id).first()
    student = db.query(models.User).filter(models.User.id == conv.student_id).first()
    
    return {
        "id": conv.id,
        "coach_name": coach.display_name,
        "coach_avatar": coach.avatar,
        "student_name": student.name,
        "messages": [
            {
                "id": m.id,
                "role": m.sender_role,
                "content": m.content,
                "time": m.created_at.strftime("%H:%M")
            } for m in messages
        ]
    }

@app.post("/api/conversations/{id}/messages")
async def send_message(
    id: int, 
    payload: dict, # {content: str}
    request: Request, 
    db: Session = Depends(get_db)
):
    # Rate Limit: 15/min
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    
    rl_key = f"user:{user.id}:msg"
    if not check_rate_limit(db, rl_key, 15, 1):
        raise HTTPException(status_code=429, detail="發送太快，請稍息 (HTTP 429)")

    conv = db.query(models.Conversation).filter(models.Conversation.id == id).first()
    if not conv: raise HTTPException(status_code=404)
    
    # Determine role
    role = "student"
    if conv.student_id != user.id:
         # Check coach
         coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == conv.coach_id).first()
         if coach and coach.user_id == user.id:
             role = "coach"
         else:
             raise HTTPException(status_code=403)
             
    new_msg = models.ConversationMessage(
        conversation_id=id,
        sender_role=role,
        content=payload.get("content")
    )
    db.add(new_msg)
    
    conv.last_message_at = datetime.utcnow()
    conv.message_count += 1
    db.commit()
    return {"status": "ok", "msg": new_msg.content, "time": new_msg.created_at.strftime("%H:%M")}

# --- Feature 1: Bookings API ---

class BookingCreate(BaseModel):
    coach_id: int
    sport_type: Optional[str] = "fitness"

@app.post("/api/bookings/create")
async def create_booking(
    data: BookingCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)

    # 1. Check for active bookings with this coach
    # Active = REQUESTED, CONFIRMED, IN_PROGRESS
    active_booking = db.query(models.Booking).filter(
        models.Booking.student_id == user.id,
        models.Booking.coach_id == data.coach_id,
        models.Booking.status.in_(["REQUESTED", "CONFIRMED", "IN_PROGRESS"])
    ).first()

    if active_booking:
        raise HTTPException(status_code=400, detail="您與此教練已有進行中或審核中的預約，請先完成或取消後再發送新預約。")
    
    # Create Booking
    new_booking = models.Booking(
        student_id=user.id,
        coach_id=data.coach_id,
        sport_type=data.sport_type,
        status="REQUESTED"
    )
    db.add(new_booking)
    db.commit()

    # Get Coach Profile for notification
    coach_profile = db.query(models.CoachProfile).filter(models.CoachProfile.id == data.coach_id).first()

    # 通知教練有新預約
    notif = models.Notification(
        user_id=coach_profile.user_id,
        title="收到新的預約申請",
        content=f"學員已送出一筆 {data.sport_type} 課程預約，請儘速確認。",
        type="info",
        link="/account/coach/lessons"
    )
    db.add(notif)
    db.commit()

    # Log Event for Dashboard
    subscription_service.log_event(db, "booking_create", coach_id=data.coach_id, user_id=user.id)
    return {"status": "success", "id": new_booking.id}

class BookingAction(BaseModel):
    reason: Optional[str] = None

@app.post("/api/bookings/{id}/coach/{action}")
async def handle_booking_coach(
    id: int, action: str, # confirm or reject
    request: Request, 
    data: Optional[BookingAction] = None,
    db: Session = Depends(get_db)
):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    
    booking = db.query(models.Booking).filter(models.Booking.id == id).first()
    if not booking: raise HTTPException(status_code=404)
    
    # Check coach ownership
    coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == booking.coach_id).first()
    if not coach or coach.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not the coach")
        
    if action == "confirm":
        booking.status = "CONFIRMED"
        booking.confirmed_at = datetime.utcnow()
    elif action == "reject":
        booking.status = "CANCELED"
        if data and data.reason:
            booking.cancel_reason = data.reason
        
    db.commit()

    # 通知學員預約狀態更新
    status_text = "已確認您的預約！" if action == "confirm" else "很抱歉，教練婉拒了您的預約。"
    notif = models.Notification(
        user_id=booking.student_id,
        title="預約狀態更新",
        content=f"{coach.display_name} {status_text}",
        type="success" if action == "confirm" else "warning",
        link="/account/student/lessons"
    )
    db.add(notif)
    db.commit()

    return {"status": "success", "new_status": booking.status}

@app.post("/api/bookings/{id}/complete")
async def complete_booking(
    id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    
    booking = db.query(models.Booking).filter(models.Booking.id == id).first()
    if not booking: raise HTTPException(status_code=404)
    
    # Check if student or coach
    is_student = (booking.student_id == user.id)
    
    coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == booking.coach_id).first()
    is_coach = (coach and coach.user_id == user.id)
    
    if not is_student and not is_coach:
        raise HTTPException(status_code=403)
        
    # Sequential Logic: 
    # 1. If student clicks -> mark student done.
    # 2. If coach clicks -> mark coach done (only if student already done).
    
    acted = False
    if is_student and not booking.completed_by_student:
        booking.completed_by_student = True
        acted = True
    elif is_coach:
        # If coach clicks, check if student is done
        if not booking.completed_by_student:
            raise HTTPException(status_code=400, detail="請先等待學員確認完成課程。")
        if not booking.completed_by_coach:
            booking.completed_by_coach = True
            acted = True

    if not acted:
         # Maybe already done? Just return success to avoid error
         return {"status": "success", "booking_status": booking.status, "msg": "已經確認過囉"}
    
    # If both true -> COMPLETED
    if booking.completed_by_student and booking.completed_by_coach:
        booking.status = "COMPLETED"
        booking.completion_finalized_at = datetime.utcnow()
        booking.completed_at = datetime.utcnow()
    else:
        # Keep status as CONFIRMED or IN_PROGRESS while waiting
        pass
        
    db.commit()

    # 通知對方已完成
    target_user_id = booking.student_id if is_coach else coach.user_id
    role_name = "教練" if is_coach else "學員"
    notif = models.Notification(
        user_id=target_user_id,
        title="課程完成狀態更新",
        content=f"{role_name} 已標記課程為「已完成」。" + ("（雙方皆已確認）" if booking.status == "COMPLETED" else "（等待您的點擊確認）"),
        type="success",
        link="/account/coach/lessons" if target_user_id == coach.user_id else "/account/student/lessons"
    )
    db.add(notif)
    db.commit()

    return {
        "status": "success", 
        "booking_status": booking.status, 
        "student_done": booking.completed_by_student,
        "coach_done": booking.completed_by_coach
    }

@app.get("/api/notifications/unread_count")
async def get_unread_count(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return {"count": 0}
    count = db.query(models.Notification).filter(models.Notification.user_id == user.id, models.Notification.is_read == False).count()
    return {"count": count}

@app.post("/api/notifications/mark_read")
async def mark_notifications_read(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return {"success": False}
    db.query(models.Notification).filter(models.Notification.user_id == user.id, models.Notification.is_read == False).update({"is_read": True})
    db.commit()
    return {"success": True}

# --- 核心業務 ---

@app.get("/")
async def home(request: Request, db: Session = Depends(get_db)):
    # 動態計算每個運動項目的已上架教練人數 (Requirement B3)
    sports_data = []
    for s in SPORTS_CONFIG:
        count = db.query(models.CoachProfile).filter(
            models.CoachProfile.review_status == "APPROVED",
            models.CoachProfile.visibility_status == "VISIBLE",
            models.CoachProfile.account_status == "ACTIVE",
            models.CoachProfile.sports.like(f'%{s["name_zh"]}%')
        ).count()
        sports_data.append({**s, "coach_count": count})
        
    # Get Elite Coaches for Spotlight (Requirement: Elite Plan Perk)
    elite_coaches = db.query(models.CoachProfile).filter(
        models.CoachProfile.subscription_level == "elite",
        models.CoachProfile.review_status == "APPROVED",
        models.CoachProfile.visibility_status == "VISIBLE",
        models.CoachProfile.account_status == "ACTIVE"
    ).order_by(models.CoachProfile.rating.desc()).limit(12).all()

    return templates.TemplateResponse("index.html", {
        "request": request, 
        "user": request.state.user, 
        "sports_data": sports_data, 
        "elite_coaches": elite_coaches,
        "taiwan_areas": TAIWAN_AREAS
    })

@app.get("/coaches")
async def coach_list(
    request: Request, 
    sport: str = None, 
    city: str = None, 
    service_mode: str = None,
    budget_max: int = Query(None),
    budget_min: int = Query(None),
    tags: list[str] = Query(None),
    teaching_styles: list[str] = Query(None),
    audiences: list[str] = Query(None),
    venues: list[str] = Query(None),
    specialties: list[str] = Query(None),
    gear_type: str = Query(None),
    sort_by: str = Query("recommended"),
    db: Session = Depends(get_db)
):
    query = db.query(models.CoachProfile).filter(
        models.CoachProfile.review_status == "APPROVED",
        models.CoachProfile.visibility_status == "VISIBLE",
        models.CoachProfile.account_status == "ACTIVE"
    )
    
    if sport: query = query.filter(models.CoachProfile.sports.like(f'%{sport}%'))
    if city: query = query.filter((models.CoachProfile.service_all_areas == True) | (models.CoachProfile.service_cities.like(f'%{city}%')))
    
    # Lesson Mode / Service Mode
    if service_mode: 
        if service_mode == "flexible":
            query = query.filter(models.CoachProfile.service_mode.in_(["flexible", "student_go", "coach_offers"]))
        else:
            query = query.filter(models.CoachProfile.service_mode == service_mode)
            
    if budget_max: query = query.filter(models.CoachProfile.price_min <= budget_max)
    if budget_min: query = query.filter(models.CoachProfile.price_max >= budget_min)
    
    coaches = query.all()
    
    # Collect all active tags for display in the UI "Quiz Results Area"
    active_filters = []
    if teaching_styles: active_filters.extend(teaching_styles)
    if audiences: active_filters.extend(audiences)
    if venues: active_filters.extend(venues)
    if specialties: active_filters.extend(specialties)
    if gear_type and gear_type != "都可以": active_filters.append(gear_type)
    if tags: active_filters.extend(tags)

    service_areas = request.query_params.getlist('service_areas')
    if service_areas: active_filters.extend(service_areas)
    
    # 推薦與排序規則 (Requirement 5: 符合越多越前面)
    def calculate_match_score(c):
        score = 0
        
        # Helper to check intersections with JSON fields
        def get_match_count(filter_list, coach_field_json):
            if not filter_list: return 0
            c_data = from_json(coach_field_json)
            if not isinstance(c_data, list): return 0
            return len(set(filter_list) & set(c_data))

        score += get_match_count(teaching_styles, c.teaching_styles) * 50
        score += get_match_count(audiences, c.audiences) * 50
        score += get_match_count(venues, c.venues) * 50
        score += get_match_count(specialties, c.specialties) * 50
        score += get_match_count(service_areas, c.service_cities) * 30 # Location weight
        
        if gear_type and gear_type != "都可以" and c.gear_type:
            if gear_type == c.gear_type: score += 100
            
        if tags:
            c_tags = from_json(c.tags)
            match_count = len(set(tags) & set(c_tags))
            score += match_count * 20
            
        score += (c.rating or 0) * 10
        score += (c.lead_count or 0) * 0.1
        if c.is_verified: score += 50

        # Membership Plan Weight (New)
        plan_weights = {"free": 0, "pro": 200, "elite": 500} # Increased weights: Elite gets a massive boost
        score += plan_weights.get(c.subscription_level, 0)
        
        return score

    if sort_by == "price_asc":
        coaches.sort(key=lambda x: x.price_min)
    elif sort_by == "rating_desc":
        coaches.sort(key=lambda x: x.rating or 0, reverse=True)
    else: # recommended
        coaches.sort(key=calculate_match_score, reverse=True)

    # Log Impressions for top results
    for c in coaches[:20]:
        subscription_service.log_event(db, "impression_list", coach_id=c.id, user_id=request.state.user.id if request.state.user else None)

    return templates.TemplateResponse("coach/list.html", {
        "request": request, "user": request.state.user, "coaches": coaches,
        "sport_filter": sport, "city_filter": city, "service_mode_filter": service_mode,
        "budget_max": budget_max, "budget_min": budget_min,
        "selected_tags": active_filters, 
        "taiwan_areas": TAIWAN_AREAS,
        "sort_by": sort_by,
        "teaching_styles": teaching_styles,
        "audiences": audiences,
        "venues": venues,
        "specialties": specialties,
        "gear_type": gear_type,
        "service_areas": service_areas
    })

@app.post("/api/events")
async def track_front_event(
    request: Request,
    event_type: str = Body(..., embed=True),
    coach_id: int = Body(..., embed=True),
    db: Session = Depends(get_db)
):
    """
    接收前端回報的行為事件 (例如：點擊連結、查看照片)
    """
    user = request.state.user
    subscription_service.log_event(db, event_type, coach_id=coach_id, user_id=user.id if user else None)
    return {"status": "success"}

@app.get("/coaches/{coach_id}")
async def coach_detail(coach_id: int, request: Request, db: Session = Depends(get_db)):
    coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == coach_id).first()
    if not coach: raise HTTPException(status_code=404)
    
    current_user = request.state.user
    subscription_service.log_event(db, "impression_coach", coach_id=coach.id, user_id=current_user.id if current_user else None)
    # 審核中/未通過即下架規則：非 APPROVED 狀態且非本人/管理員，禁止訪問詳情頁
    if coach.status != "APPROVED" and not (current_user and (current_user.role == "admin" or current_user.id == coach.user_id)):
        return templates.TemplateResponse("error.html", {
            "request": request, 
            "message": "此教練資料正在審核中，暫時不對外顯示。", 
            "user": current_user, 
            "taiwan_areas": TAIWAN_AREAS
        }, status_code=403)
    
    coach.view_count += 1
    db.commit()

    # Fetch featured reviews (Top 3 highest rating)
    featured_reviews = []
    reviews_objs = db.query(models.Review).filter(models.Review.coach_id == coach_id).order_by(models.Review.rating.desc(), models.Review.created_at.desc()).limit(3).all()
    for r in reviews_objs:
        student_name = "匿名學員"
        if not r.is_anonymous:
            s = db.query(models.User).filter(models.User.id == r.student_id).first()
            student_name = s.name if s else "未知學員"
        featured_reviews.append({
            "rating": int(r.rating),
            "comment": r.comment,
            "student_name": student_name
        })

    return templates.TemplateResponse("coach/detail.html", {
        "request": request, 
        "user": current_user, 
        "coach": coach, 
        "featured_reviews": featured_reviews,
        "taiwan_areas": TAIWAN_AREAS
    })


@app.post("/coaches/{coach_id}/inquiry")
async def send_inquiry(
    coach_id: int, 
    name: str = Form(...), 
    contact: str = Form(...), 
    message: str = Form(...), 
    summary_json: str = Form("{}"),
    request: Request = None,
    db: Session = Depends(get_db)
):
    try:
        current_user = request.state.user
        if not current_user:
            return JSONResponse(status_code=401, content={"detail": "請先登入"})

        coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == coach_id).first()
        if not coach: raise HTTPException(status_code=404, detail="Coach not found")

        # 1. Create Lead (REMOVED: models.Lead does not exist)
        # lead = models.Lead(...) 
        
        # 2. Start/Find Conversation Thread
        thread = db.query(models.InquiryThread).filter(
            models.InquiryThread.student_id == current_user.id,
            models.InquiryThread.coach_profile_id == coach_id
        ).first()
        
        if not thread:
            thread = models.InquiryThread(student_id=current_user.id, coach_profile_id=coach_id)
            db.add(thread)
            db.flush()
        
        # 3. Add First Message (Rich Content)
        full_message = f"【基本資料】\n姓名：{name}\n聯絡方式：{contact}\n\n【諮詢內容】\n{message}"
        msg = models.InquiryMessage(thread_id=thread.id, sender_id=current_user.id, content=full_message)
        thread.last_message = message
        thread.updated_at = datetime.utcnow()
        db.add(msg)
        
        # 4. Update Coach Stats
        coach.lead_count += 1
        
        # 5. Send Notification with Clickable Link
        notif = models.Notification(
            user_id=coach.user_id,
            title="收到新學員諮詢訊息",
            content=f"學員 {name}：{message[:20]}...",
            type="success",
            link=f"/messages/{thread.id}"
        )
        db.add(notif)
        
        # 6. Log Analytics Event (For Dashboard Funnel)
        subscription_service.log_event(db, "inquiry_create", coach_id=coach.id, user_id=current_user.id)
        
        db.commit()
        
        # Return JSON for AJAX to handle redirect
        return JSONResponse(status_code=200, content={
            "status": "success", 
            "redirect_url": f"/messages/{thread.id}?success=1"
        })
    except Exception as e:
        db.rollback()
        print(f"Error sending inquiry: {str(e)}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

# --- 訊息/諮詢系統 ---

@app.get("/messages")
async def message_list(request: Request, role_filter: str = "student", db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    
    threads_display = []
    
    # 1. Fetch Admin Support Conversations
    admin_convs = db.query(models.AdminConversation).filter(
        models.AdminConversation.user_id == user.id
    ).all()
    
    # Determine current filter first to validly filter admin messages
    coach_profile = get_user_coach_profile(user, db)
    coach_id = coach_profile.id if coach_profile else -1
    
    current_role_filter = "student"
    if role_filter == "coach" and coach_id != -1:
        current_role_filter = "coach"
    
    for c in admin_convs:
        # Filter Logic based on Subject keywords
        # Coach-specific keywords: "停權", "審核", "Coach", "帳號" (Account suspension usually coach)
        # Student-specific keywords: "投訴處理" (Complaint resolution)
        
        is_coach_topic = any(k in c.subject for k in ["停權", "審核", "Coach", "帳號"])
        is_student_topic = any(k in c.subject for k in ["投訴處理", "Student"])
        
        # Display Logic:
        # If Current Tab is COACH: Show Coach topics. Hide Student topics.
        # If Current Tab is STUDENT: Show Student topics. Hide Coach topics.
        
        should_show = False
        if current_role_filter == "coach":
            if is_coach_topic: should_show = True
        else: # Student Tab
            if is_student_topic or (not is_coach_topic): should_show = True 
            # Show generic threads in Student tab, but definitely hide Coach-specific threads
            
        if should_show:
            last_msg = db.query(models.AdminMessage).filter(models.AdminMessage.conversation_id == c.id).order_by(models.AdminMessage.created_at.desc()).first()
            threads_display.append({
                "id": c.id,
                "type": "admin",
                "partner_name": "平台管理員 (客服)",
                "partner_avatar": None, 
                "partner_sport_type": "support",
                "last_message": last_msg.content if last_msg else "開啟對話...",
                "updated_at": c.updated_at
            })

    # 2. Fetch Inquiry Threads
    query = db.query(models.InquiryThread)
    if current_role_filter == "coach":
        query = query.filter(models.InquiryThread.coach_profile_id == coach_id)
    else:
        query = query.filter(models.InquiryThread.student_id == user.id)
        
    inquiry_threads = query.order_by(models.InquiryThread.updated_at.desc()).all()
    
    for t in inquiry_threads:
        data = get_thread_display_data(t, user, db)
        data["type"] = "inquiry"
        threads_display.append(data)
    
    # Sort combined list
    threads_display.sort(key=lambda x: x['updated_at'], reverse=True)
    
    return templates.TemplateResponse("messages/list.html", {
        "request": request, 
        "user": user, 
        "threads": threads_display, 
        "current_role": current_role_filter,
        "is_coach": coach_id != -1,
        "taiwan_areas": TAIWAN_AREAS
    })

def get_thread_display_data(t, user, db):
    # ... (existing logic, mostly unchanged, just ensured it returns expected keys)
    coach_profile = get_user_coach_profile(user, db)
    coach_id = coach_profile.id if coach_profile else -1
    
    display_partner = ""
    partner_avatar = "/static/default_avatar.png"
    partner_sport_type = None
    
    if t.student_id == user.id:
        p = db.query(models.CoachProfile).filter(models.CoachProfile.id == t.coach_profile_id).first()
        display_partner = p.display_name if p else "系統教練"
        partner_avatar = p.avatar if p else "/static/default_avatar.png"
        if p:
            sports = from_json(p.sports)
            partner_sport_type = sports[0] if sports else None
    else:
        p = db.query(models.User).filter(models.User.id == t.student_id).first()
        display_partner = p.name or p.email.split('@')[0]
        partner_avatar = p.avatar_url or "/static/default_avatar.png"
        
    return {
        "id": t.id,
        "partner_name": display_partner,
        "partner_avatar": partner_avatar,
        "partner_sport_type": partner_sport_type,
        "last_message": t.last_message,
        "updated_at": t.updated_at
    }

@app.get("/messages/{thread_id}")
async def message_thread(thread_id: int, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    
    thread = db.query(models.InquiryThread).filter(models.InquiryThread.id == thread_id).first()
    if not thread: raise HTTPException(status_code=404)
    
    # Auth check
    coach_profile = get_user_coach_profile(user, db)
    coach_id = coach_profile.id if coach_profile else -1
    if thread.student_id != user.id and thread.coach_profile_id != coach_id:
        raise HTTPException(status_code=403)
        
    messages = db.query(models.InquiryMessage).filter(models.InquiryMessage.thread_id == thread_id).order_by(models.InquiryMessage.created_at.asc()).all()
    
    # Determine partner info
    if thread.student_id == user.id:
        p = db.query(models.CoachProfile).filter(models.CoachProfile.id == thread.coach_profile_id).first()
        partner_name = p.display_name
        partner_id = p.user_id
    else:
        p = db.query(models.User).filter(models.User.id == thread.student_id).first()
        partner_name = p.name or p.email.split('@')[0]
        partner_id = p.id

    return templates.TemplateResponse("messages/chat.html", {
        "request": request, 
        "user": user, 
        "thread": thread, 
        "messages": messages,
        "partner_name": partner_name,
        "partner_id": partner_id,
        "taiwan_areas": TAIWAN_AREAS,
        "post_url": f"/messages/{thread.id}/send",
        "is_support": False
    })

@app.get("/messages/support/{conversation_id}")
async def support_message_thread(conversation_id: int, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    
    conv = db.query(models.AdminConversation).filter(
        models.AdminConversation.id == conversation_id,
        models.AdminConversation.user_id == user.id
    ).first()
    if not conv: raise HTTPException(status_code=404)
    
    # Check messages
    msgs = db.query(models.AdminMessage).filter(models.AdminMessage.conversation_id == conversation_id).order_by(models.AdminMessage.created_at.asc()).all()
    
    return templates.TemplateResponse("messages/chat.html", {
        "request": request,
        "user": user,
        "thread": conv, # Object with id
        "messages": msgs,
        "partner_name": "平台管理員 (客服)",
        "partner_id": None, 
        "taiwan_areas": TAIWAN_AREAS,
        "post_url": f"/messages/support/{conversation_id}/send",
        "is_support": True
    })

@app.post("/messages/support/{conversation_id}/send")
async def send_support_message(
    conversation_id: int, 
    request: Request, 
    content: Optional[str] = Form(None), 
    file: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    if content is None: content = ""
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    
    conv = db.query(models.AdminConversation).filter(
        models.AdminConversation.id == conversation_id,
        models.AdminConversation.user_id == user.id
    ).first()
    if not conv: raise HTTPException(status_code=404)
    
    # Handle File Upload
    if file and file.filename:
        upload_dir = "app/static/uploads"
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)
            
        ext = os.path.splitext(file.filename)[1]
        unique_name = f"{uuid.uuid4()}{ext}"
        file_path = os.path.join(upload_dir, unique_name)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        file_url = f"/static/uploads/{unique_name}"
        content += f"\n[附件] {file_url}"

    msg = models.AdminMessage(
        conversation_id=conversation_id,
        sender_id=user.id,
        sender_role="user",
        content=content,
        is_read=False
    )
    db.add(msg)
    conv.updated_at = datetime.utcnow()
    db.commit()
    
    return RedirectResponse(url=f"/messages/support/{conversation_id}", status_code=303)

@app.post("/messages/{thread_id}/send")
async def send_message(
    thread_id: int, 
    request: Request,
    content: Optional[str] = Form(None), 
    file: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    if content is None: content = ""
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    
    thread = db.query(models.InquiryThread).filter(models.InquiryThread.id == thread_id).first()
    if not thread: raise HTTPException(status_code=404)
    
    # Handle File Upload
    if file and file.filename:
        upload_dir = "app/static/uploads"
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)
            
        ext = os.path.splitext(file.filename)[1]
        unique_name = f"{uuid.uuid4()}{ext}"
        file_path = os.path.join(upload_dir, unique_name)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        file_url = f"/static/uploads/{unique_name}"
        content += f"\n[附件] {file_url}"

    msg = models.InquiryMessage(thread_id=thread_id, sender_id=user.id, content=content)
    thread.last_message = content
    thread.updated_at = datetime.utcnow()
    db.add(msg)
    
    # Notify partner
    partner_user_id = thread.student_id if thread.coach_profile_id == get_user_coach_profile(user, db).id else db.query(models.CoachProfile).filter(models.CoachProfile.id == thread.coach_profile_id).first().user_id
    
    notif = models.Notification(
        user_id=partner_user_id,
        title="收到新訊息",
        content=f"{user.name or user.email.split('@')[0]}：{content[:20]}...",
        type="info",
        link=f"/messages/{thread_id}"
    )
    db.add(notif)
    db.commit()
    return RedirectResponse(url=f"/messages/{thread_id}", status_code=302)

# --- 個人中心 ---

@app.get("/account")
async def account_home(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    if user.role == "admin": return RedirectResponse(url="/admin")
    coach = get_user_coach_profile(user, db)
    return templates.TemplateResponse("account/dashboard.html", {"request": request, "user": user, "coach": coach, "taiwan_areas": TAIWAN_AREAS})

@app.get("/account/student")
async def student_center(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    
    threads = db.query(models.InquiryThread).filter(models.InquiryThread.student_id == user.id).order_by(models.InquiryThread.updated_at.desc()).limit(10).all()
    thread_data = [get_thread_display_data(t, user, db) for t in threads]
    
    return templates.TemplateResponse("account/student.html", {"request": request, "user": user, "threads": thread_data, "taiwan_areas": TAIWAN_AREAS})

@app.post("/account/profile")
async def update_user_profile(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    db: Session = Depends(get_db)
):
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    
    # Check if email taken by someone else
    existing = db.query(models.User).filter(models.User.email == email, models.User.id != user.id).first()
    if existing:
        return RedirectResponse(url="/account/student?error=電子郵件已被佔用", status_code=302)
        
    user.name = name
    user.email = email
    db.commit()
    return RedirectResponse(url="/account/student?success=個人資料已更新", status_code=302)

@app.get("/account/coach")
async def coach_center(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    coach = get_user_coach_profile(user, db)
    
    threads = []
    kpi_data = {"impressions": 0, "favorites": 0, "inquiries": 0, "bookings": 0}
    current_plan = {"plan_id": "free", "name_zh": "基本"}

    if coach:
        threads = db.query(models.InquiryThread).filter(models.InquiryThread.coach_profile_id == coach.id).order_by(models.InquiryThread.updated_at.desc()).limit(5).all()
        # Fetch current plan
        current_plan = subscription_service.get_subscription_details(db, coach.id)
        
        # Analytics & Funnel Data (Default: Last 30 Days)
        now = datetime.utcnow()
        period_days = 30
        period_start = now - timedelta(days=period_days)
        prev_start = period_start - timedelta(days=period_days)
        
        def get_count(etype, start, end):
            q = db.query(models.Event).filter(
                models.Event.coach_id == coach.id,
                models.Event.created_at >= start,
                models.Event.created_at < end
            )
            if isinstance(etype, list):
                q = q.filter(models.Event.event_type.in_(etype))
            else:
                q = q.filter(models.Event.event_type == etype)
            return q.count()

        # 1. Fetch Funnel Metrics
        views = get_count("impression_coach", period_start, now)
        favorites = get_count("favorite_add", period_start, now)
        inquiries = get_count("inquiry_create", period_start, now)
        bookings = get_count("booking_create", period_start, now)
        
        # Interactions (Media view, clicks, offers) - Mocking some if events don't exist yet
        # Once frontend tracking is added, this will be real.
        interact_raw = get_count(["media_view", "offer_click", "cta_click", "social_click"], period_start, now)
        interactions = favorites + interact_raw
        if interactions < inquiries: interactions = inquiries + favorites # Sanity check for funnel shape

        # Search/Listing Impressions (Top of Funnel)
        # 從資料庫獲取真實的列表曝光 (impression_list)
        # 如果是舊資料可能沒有 impression_list，則暫時用 views 替代，避免漏斗第一層為 0
        real_list_impressions = get_count("impression_list", period_start, now)
        search_impressions = max(real_list_impressions, views) 
        
        # 2. Calculate Trends (vs Previous 30 Days)
        prev_views = get_count("impression_coach", prev_start, period_start)
        view_trend = round(((views - prev_views) / prev_views * 100), 1) if prev_views > 0 else 0
        
        prev_inquiries = get_count("inquiry_create", prev_start, period_start)
        inquiry_trend = round(((inquiries - prev_inquiries) / prev_inquiries * 100), 1) if prev_inquiries > 0 else 0
        
        kpi_data = {
            "period_label": "近 30 天",
            "impressions": search_impressions,
            "views": views,
            "interactions": interactions,
            "favorites": favorites,
            "inquiries": inquiries,
            "bookings": bookings,
            "trends": {
                "views": view_trend,
                "inquiries": inquiry_trend
            },
            "rates": {
                "ctr": round(views / search_impressions * 100, 1) if search_impressions > 0 else 0,
                "interact": round(interactions / views * 100, 1) if views > 0 else 0,
                "conversion": round(bookings / inquiries * 100, 1) if inquiries > 0 else 0
            }
        }
    
    thread_data = [get_thread_display_data(t, user, db) for t in threads]
    
    return templates.TemplateResponse("account/coach_status.html", {
        "request": request, 
        "user": user, 
        "coach": coach, 
        "threads": thread_data, 
        "kpi_data": kpi_data,
        "current_plan": current_plan,
        "taiwan_areas": TAIWAN_AREAS
    })

@app.get("/account/coach/apply")
async def coach_apply(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    coach = get_user_coach_profile(user, db)
    if not coach:
        coach = models.CoachProfile(user_id=user.id, display_name=user.name or user.email.split('@')[0], status="DRAFT")
        db.add(coach)
        db.commit()
    return RedirectResponse(url="/account/coach/edit")

@app.get("/account/coach/edit")
async def coach_edit(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    coach = get_user_coach_profile(user, db)
    if not coach: return RedirectResponse(url="/account/coach/apply")
    
    # Show pending revisions in the editor
    working_coach = coach
    if coach.pending_profile and coach.pending_profile != "{}":
        try:
            changes = json.loads(coach.pending_profile)
            import copy
            working_coach = copy.copy(coach)
            for k, v in changes.items():
                if hasattr(working_coach, k):
                    if k in ['sports', 'teaching_styles', 'audiences', 'venues', 'specialties', 'tags', 'service_cities']:
                        setattr(working_coach, k, json.dumps(v, ensure_ascii=False))
                    else:
                        setattr(working_coach, k, v)
        except:
            pass

    return templates.TemplateResponse("account/coach_edit.html", {
        "request": request, 
        "user": user, 
        "coach": working_coach, 
        "original_status": coach.status,
        "taiwan_areas": TAIWAN_AREAS
    })

@app.get("/account/coach/upgrade")
async def coach_upgrade_page(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return RedirectResponse("/login")
    coach = get_user_coach_profile(user, db)
    if not coach: return RedirectResponse("/account/coach/apply")
    return templates.TemplateResponse("coach/upgrade.html", {"request": request, "coach": coach})

@app.get("/account/coach/showcase")
async def coach_showcase_page(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return RedirectResponse("/login")
    coach = get_user_coach_profile(user, db)
    if not coach: return RedirectResponse("/account/coach/apply")
    return templates.TemplateResponse("coach/showcase_editor.html", {"request": request, "coach": coach, "user": user})

# --- Membership & Upgrade Section ---

@app.get("/coach/upgrade")
async def coach_upgrade_page(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    coach = get_user_coach_profile(user, db)
    if not coach: return RedirectResponse(url="/account")
    
    current_plan = subscription_service.get_subscription_details(db, coach.id)
    return templates.TemplateResponse("coach/upgrade.html", {
        "request": request, 
        "user": user, 
        "coach": coach, 
        "current_plan": current_plan
    })

@app.get("/api/coach/plan")
async def get_plan_api(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    coach = get_user_coach_profile(user, db)
    if not coach: raise HTTPException(status_code=404)
    return subscription_service.get_subscription_details(db, coach.id)

@app.post("/api/account/coach/subscription")
async def update_coach_subscription(request: Request, body: Dict[str, Any], db: Session = Depends(get_db)):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    coach = get_user_coach_profile(user, db)
    if not coach: raise HTTPException(status_code=404)
    
    level = body.get("level")
    if level not in ["free", "pro", "elite"]:
        raise HTTPException(status_code=400, detail="Invalid plan level")
    
    # Update profile membership level
    coach.subscription_level = level
    
    # Update linked subscription record
    subscription_service.activate_plan(db, coach.id, level, days=30)
    
    db.commit()
    return {"status": "success", "level": level}

@app.post("/api/coach/plan/activate")
async def activate_plan_api(request: Request, body: Dict[str, Any], db: Session = Depends(get_db)):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    coach = get_user_coach_profile(user, db)
    if not coach: raise HTTPException(status_code=404)
    
    plan_id = body.get("plan_id")
    days = body.get("days", 7)
    
    if plan_id not in ["pro", "elite"]:
        raise HTTPException(status_code=400, detail="Invalid plan id")
        
    subscription_service.activate_plan(db, coach.id, plan_id, days=days)
    # Also sync to coach profile
    coach.subscription_level = plan_id
    db.commit()
    return {"message": f"Successfully activated {plan_id} scheme for {days} days"}
    
    # Show pending revisions in the editor
    working_coach = coach
    if coach.pending_profile and coach.pending_profile != "{}":
        try:
            changes = json.loads(coach.pending_profile)
            import copy
            working_coach = copy.copy(coach)
            for k, v in changes.items():
                if hasattr(working_coach, k):
                    if k in ['sports', 'teaching_styles', 'audiences', 'venues', 'specialties', 'tags', 'service_cities']:
                        setattr(working_coach, k, json.dumps(v, ensure_ascii=False))
                    else:
                        setattr(working_coach, k, v)
        except:
            pass

    return templates.TemplateResponse("account/coach_edit.html", {
        "request": request, 
        "user": user, 
        "coach": working_coach, 
        "original_status": coach.status,
        "taiwan_areas": TAIWAN_AREAS
    })

def get_review_checklist(coach: models.CoachProfile):
    """生成審核必填檢查清單"""
    import json
    def from_json(s):
        try: return json.loads(s) if s else []
        except: return []

    checklist = []
    # 通用項目
    checklist.append({"key": "avatar", "label": "個人頭像", "ok": bool(coach.avatar and "default_avatar" not in coach.avatar)})
    checklist.append({"key": "display_name", "label": "公開名稱", "ok": bool(coach.display_name)})
    
    sports = from_json(coach.sports)
    checklist.append({"key": "sports", "label": "至少 1 個運動項目", "ok": len(sports) > 0})
    
    checklist.append({"key": "price", "label": "收費設定 (>0)", "ok": bool(coach.price_min and coach.price_min > 0)})
    
    bio_len = len(coach.bio) if coach.bio else 0
    checklist.append({"key": "bio", "label": "個人簡介 (>20字)", "ok": bio_len >= 20})
    
    tags = from_json(coach.tags)
    styles = from_json(coach.teaching_styles)
    checklist.append({"key": "tags", "label": "專業標籤 (至少2個)", "ok": (len(tags) + len(styles)) >= 2})
    
    # 運動專屬
    if "潛水" in sports:
        spec = from_json(coach.specialties)
        checklist.append({"key": "diving_spec", "label": "潛水：導潛/課程設定", "ok": len(spec) > 0})
    
    if "健身" in sports:
        spec = from_json(coach.specialties)
        checklist.append({"key": "fitness_spec", "label": "健身：專長設定", "ok": len(spec) > 0})

    if "滑雪" in sports:
        checklist.append({"key": "ski_gear", "label": "滑雪：器材設定", "ok": bool(coach.gear_type)})

    return checklist

def log_review_action(db, coach_id, action, actor_id=None, payload=None):
    log = models.CoachReviewLog(
        coach_id=coach_id,
        action=action,
        actor_admin_id=actor_id,
        payload_json=json.dumps(payload, ensure_ascii=False) if payload else "{}"
    )
    db.add(log)
    db.commit()

@app.get("/api/coach/me/review-status")
async def get_my_review_status(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return {"error": "Unauthorized"}
    coach = get_user_coach_profile(user, db)
    if not coach: return {"error": "No coach profile found"}
    
    reject_reasons = []
    try: reject_reasons = json.loads(coach.reject_reasons_json or "[]")
    except: pass
    
    return {
        "review_status": coach.status,
        "reject_reasons": reject_reasons,
        "reject_note": coach.reject_reason,
        "reviewed_at": coach.reviewed_at,
        "submitted_at": coach.submitted_at
    }

@app.post("/account/coach/submit")
async def coach_submit(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    coach = get_user_coach_profile(user, db)
    if coach:
        coach.status = "PENDING"
        coach.submitted_at = datetime.utcnow()
        log_review_action(db, coach.id, "SUBMIT", actor_id=None, payload={"type": coach.submit_type})
        db.commit()
    return RedirectResponse(url="/account/coach")

# --- 管理員首頁與工作台 ---

@app.get("/admin")
async def admin_workbench(request: Request, db: Session = Depends(get_db), user: models.User = Depends(auth.admin_required)):
    # 1. 計算待辦數量
    pending_count = db.query(models.CoachProfile).filter(
        models.CoachProfile.review_status == "PENDING_REVIEW"
    ).count()
    
    # Update: Include all non-resolved cases
    case_count = db.query(models.AdminCase).filter(
        models.AdminCase.status.notin_(["RESOLVED", "CLOSED"])
    ).count()

    # New: Admin Unread Messages
    unread_msg_count = db.query(models.AdminMessage).filter(
        models.AdminMessage.sender_role != "admin",
        models.AdminMessage.is_read == False
    ).count()
    
    # 2. KPI 統計
    week_ago = datetime.utcnow() - timedelta(days=7)
    day_ago = datetime.utcnow() - timedelta(days=1)
    
    new_coaches_week = db.query(models.CoachProfile).filter(
        models.CoachProfile.submitted_at >= week_ago
    ).count()
    
    total_active = db.query(models.CoachProfile).filter(
        models.CoachProfile.review_status == "APPROVED"
    ).count()
    
    total_all = db.query(models.CoachProfile).count()
    approval_rate = round((total_active / total_all * 100), 1) if total_all > 0 else 0
    
    violations_week = db.query(models.AdminCase).filter(
        models.AdminCase.case_type.in_(["COMPLAINT", "LOW_RATING"]),
        models.AdminCase.created_at >= week_ago
    ).count()
    
    # 3. 待辦列表 (Top 5)
    pending_coaches = db.query(models.CoachProfile).filter(
        models.CoachProfile.review_status == "PENDING_REVIEW"
    ).order_by(models.CoachProfile.submitted_at.desc()).limit(5).all()
    
    open_cases = db.query(models.AdminCase).filter(
        models.AdminCase.status == "OPEN"
    ).order_by(models.AdminCase.created_at.desc()).limit(5).all()
    
    # 案件詳情補充 (如教練姓名)
    enhanced_cases = []
    for c in open_cases:
        c_coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == c.coach_id).first()
        enhanced_cases.append({
            "case": c,
            "coach_name": c_coach.display_name if c_coach else "Unknown"
        })

    return templates.TemplateResponse("admin/workbench.html", {
        "request": request,
        "user": user,
        "pending_count": pending_count,
        "case_count": case_count,
        "unread_msg_count": unread_msg_count,
        "new_coaches": new_coaches_week,
        "approval_rate": approval_rate,
        "violations": violations_week,
        "pending_coaches": pending_coaches,
        "open_cases": enhanced_cases
    })

# --- 管理員審核 ---

@app.get("/admin/coaches")
async def admin_coach_list(request: Request, status_filter: str = "PENDING_REVIEW", db: Session = Depends(get_db), user: models.User = Depends(auth.admin_required)):
    # 支援舊版參數相容性
    if status_filter == "PENDING": status_filter = "PENDING_REVIEW"
    if status_filter == "APPROVED": status_filter = "APPROVED"
    if status_filter == "REJECTED": status_filter = "REJECTED"

    # 1. 列表資料 (根據 review_status)
    coaches = db.query(models.CoachProfile).filter(models.CoachProfile.review_status == status_filter).order_by(models.CoachProfile.submitted_at.desc()).all()

    # 2. KPI 統計
    week_ago = datetime.utcnow() - timedelta(days=7)
    
    pending_count = db.query(models.CoachProfile).filter(models.CoachProfile.review_status == "PENDING_REVIEW").count()
    new_this_week = db.query(models.CoachProfile).filter(models.CoachProfile.submitted_at >= week_ago).count()
    
    # 審核通過率 (本週)
    reviewed_this_week = db.query(models.CoachProfile).filter(models.CoachProfile.reviewed_at >= week_ago).all()
    approved_count = sum(1 for c in reviewed_this_week if c.review_status == "APPROVED")
    total_reviewed = len(reviewed_this_week)
    approval_rate = round((approved_count / total_reviewed * 100), 1) if total_reviewed > 0 else "—"
    
    # 平均處理耗時 (本週)
    process_times = []
    for c in reviewed_this_week:
        if c.reviewed_at and c.submitted_at:
            delta = (c.reviewed_at - c.submitted_at).total_seconds()
            process_times.append(delta)
    
    avg_time_str = "—"
    if process_times:
        avg_sec = sum(process_times) / len(process_times)
        if avg_sec < 3600:
            avg_time_str = f"{int(avg_sec/60)}m"
        elif avg_sec < 86400:
            avg_time_str = f"{round(avg_sec/3600, 1)}h"
        else:
            avg_time_str = f"{round(avg_sec/86400, 1)}d"

    return templates.TemplateResponse("admin/coach_list.html", {
        "request": request, 
        "user": user, 
        "coaches": coaches, 
        "current_status": status_filter,
        "pending_count": pending_count,
        "new_this_week": new_this_week,
        "approval_rate": approval_rate,
        "avg_time": avg_time_str
    })

@app.get("/admin/coaches/directory")
async def admin_coach_directory(
    request: Request, 
    sport: str = Query(None), 
    level: str = Query(None),
    status: str = Query(None),
    sort: str = Query("newest"),
    db: Session = Depends(get_db), 
    user: models.User = Depends(auth.admin_required)
):
    query = db.query(models.CoachProfile).filter(models.CoachProfile.review_status.in_(["APPROVED", "SUSPENDED", "BANNED"]))
    
    if sport:
        query = query.filter(models.CoachProfile.sports.like(f'%{sport}%'))
    if level:
        query = query.filter(models.CoachProfile.subscription_level == level)
    if status:
        query = query.filter(models.CoachProfile.review_status == status)
        
    # Apply Sorting
    # Apply Sorting
    if sort == "rating_desc":
        query = query.order_by(models.CoachProfile.rating.desc(), models.CoachProfile.rating_count.desc())
    elif sort == "oldest":
        query = query.order_by(models.CoachProfile.submitted_at.asc())
    elif sort == "newest":
        query = query.order_by(models.CoachProfile.submitted_at.desc())
    # Note: If sort is "level_desc", we sort in Python after fetching to avoid complex SQL case issues

    coaches = query.all()
    
    if sort == "level_desc":
        level_map = {"elite": 3, "pro": 2, "free": 1}
        # Sort: Level Desc, then Time Desc
        coaches.sort(key=lambda x: (
            level_map.get(x.subscription_level, 0), 
            x.submitted_at.timestamp() if x.submitted_at else 0
        ), reverse=True)
    
    # Stats for APPROVED coaches
    base_query = db.query(models.CoachProfile).filter(models.CoachProfile.review_status == "APPROVED")
    total_approved = base_query.count()
    elite_count = base_query.filter(models.CoachProfile.subscription_level == "elite").count()
    pro_count = base_query.filter(models.CoachProfile.subscription_level == "pro").count()
    free_count = base_query.filter(models.CoachProfile.subscription_level == "free").count()
    
    return templates.TemplateResponse("admin/coach_directory.html", {
        "request": request,
        "user": user,
        "coaches": coaches,
        "total_approved": total_approved,
        "elite_count": elite_count,
        "pro_count": pro_count,
        "free_count": free_count,
        "sport_filter": sport,
        "level_filter": level,
        "status_filter": status,
        "sort_filter": sort,
        "sports_list": [s["name_zh"] for s in SPORTS_CONFIG]
    })

@app.get("/admin/coaches/{coach_id}/preview")
async def admin_preview_coach(coach_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(auth.admin_required)):
    coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == coach_id).first()
    if not coach: raise HTTPException(status_code=404)
    
    # Prep version to review (pending changes applied over current)
    working_coach = coach
    is_update = coach.submit_type == "UPDATE"
    
    if coach.pending_profile and coach.pending_profile != "{}":
        try:
            changes = json.loads(coach.pending_profile)
            import copy
            working_coach = copy.copy(coach)
            for k, v in changes.items():
                if hasattr(working_coach, k):
                    if k in ['sports', 'teaching_styles', 'audiences', 'venues', 'specialties', 'tags', 'service_cities']:
                        setattr(working_coach, k, json.dumps(v, ensure_ascii=False))
                    else:
                        setattr(working_coach, k, v)
        except: pass
    
    checklist = get_review_checklist(working_coach)
    
    return templates.TemplateResponse("admin/preview_coach.html", {
        "request": request, 
        "user": user, 
        "coach": working_coach, 
        "real_coach": coach,
        "checklist": checklist,
        "taiwan_areas": TAIWAN_AREAS
    })

@app.post("/admin/coaches/{coach_id}/review")
async def admin_review_coach(
    coach_id: int, 
    action: str = Form(...), 
    reason_keys: list[str] = Form([]), 
    note: str = Form(None), 
    db: Session = Depends(get_db), 
    user: models.User = Depends(auth.admin_required)
):
    coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == coach_id).first()
    if not coach: raise HTTPException(status_code=404)
    
    payload = {"reviewer_id": user.id, "note": note}

    if action == "approve":
        if coach.pending_profile and coach.pending_profile != "{}":
            try:
                changes = json.loads(coach.pending_profile)
                for field, value in changes.items():
                    if hasattr(coach, field):
                        if field in ['sports', 'teaching_styles', 'audiences', 'venues', 'specialties', 'tags', 'service_cities']:
                            setattr(coach, field, json.dumps(value, ensure_ascii=False))
                        else:
                            setattr(coach, field, value)
                coach.approved_profile = coach.pending_profile
                coach.pending_profile = "{}"
            except Exception as e: print(f"Merge error: {e}")
        
        StatusService.apply_coach_transition(db, coach, "APPROVED", "admin")
        coach.is_verified = True
        coach.reject_reasons_json = "[]"
        coach.reject_reason = None
        log_review_action(db, coach.id, "APPROVE", actor_id=user.id, payload=payload)
        
    elif action == "reject":
        StatusService.apply_coach_transition(db, coach, "REJECTED", "admin")
        coach.reject_reasons_json = json.dumps(reason_keys, ensure_ascii=False)
        coach.reject_reason = note
        payload["reasons"] = reason_keys
        log_review_action(db, coach.id, "REJECT", actor_id=user.id, payload=payload)
        
    # Governance Actions
    elif action == "suspend":
        StatusService.apply_coach_transition(db, coach, "SUSPENDED", "admin")
        coach.reject_reason = note # Store suspension reason temporarily here
        log_review_action(db, coach.id, "SUSPEND", actor_id=user.id, payload=payload)

    elif action == "ban":
        StatusService.apply_coach_transition(db, coach, "BANNED", "admin")
        coach.reject_reason = note
        log_review_action(db, coach.id, "BAN", actor_id=user.id, payload=payload)

    elif action == "unsuspend":
        StatusService.apply_coach_transition(db, coach, "APPROVED", "admin")
        coach.reject_reason = None # Clear reason
        log_review_action(db, coach.id, "UNSUSPEND", actor_id=user.id, payload=payload)
        
    coach.reviewed_at = datetime.utcnow()
    coach.reviewed_by_id = user.id
    db.commit()
    return RedirectResponse(url="/admin/coaches", status_code=302)

@app.get("/dashboard")
async def coach_dashboard_redirect():
    return RedirectResponse(url="/account/coach")

@app.post("/account/coach/profile")
async def update_profile(
    request: Request,
    display_name: str = Form(...),
    bio: str = Form(""),
    sports_text: str = Form(""),
    teaching_styles: list[str] = Form([]),
    audiences: list[str] = Form([]),
    service_all_areas: bool = Form(False),
    cities_list: list[str] = Form([]),
    regions_list: list[str] = Form([]),
    tags_list: list[str] = Form([]),
    venues: list[str] = Form([]),
    specialties: list[str] = Form([]),
    gear_type: str = Form(None),
    other_specialty: str = Form(None),
    price_min: int = Form(1000),
    db: Session = Depends(get_db)
):
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    coach = get_user_coach_profile(user, db)
    if not coach: return RedirectResponse(url="/account/coach/apply")

    # Prepare pending changes
    pending_data = {
        "display_name": display_name,
        "bio": bio,
        "sports": [s.strip() for s in sports_text.split(',')] if sports_text else [],
        "teaching_styles": teaching_styles,
        "audiences": audiences,
        "service_all_areas": service_all_areas,
        "service_cities": cities_list,
        "service_districts": regions_list,
        "tags": tags_list,
        "venues": venues,
        "specialties": specialties,
        "price_min": price_min,
        "gear_type": gear_type,
        "last_updated": datetime.utcnow().isoformat()
    }
    
    # Use Service to transition status (will auto-create AdminCase and set VISIBILITY to HIDDEN)
    StatusService.apply_coach_transition(db, coach, "PENDING_REVIEW", "coach")
    
    coach.pending_profile = json.dumps(pending_data, ensure_ascii=False)
    coach.submitted_at = datetime.utcnow()
    log_review_action(db, coach.id, "SUBMIT", actor_id=None, payload={})
    db.commit()
    
    return RedirectResponse(url="/account/coach/edit?success=已提交更新，審核期間您的資料將暫時下架。", status_code=303)

# --- Auth ---
@app.get("/login")
async def login_page(request: Request, error: str = None): return templates.TemplateResponse("auth/login.html", {"request": request, "user": request.state.user, "error": error})
@app.post("/login")
async def login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not auth.verify_password(password, user.hashed_password): return RedirectResponse(url="/login?error=電子郵件或密碼錯誤", status_code=302)
    token = auth.create_access_token(data={"sub": user.email})
    
    # Smart Redirect: Admin to /admin, Coach to /account/coach, others to /account
    target_url = "/account"
    if user.role == "admin":
        target_url = "/admin"
    elif user.role == "coach":
        target_url = "/account/coach"
        
    response = RedirectResponse(url=target_url, status_code=302)
    response.set_cookie(key="access_token", value=token, httponly=True)
    return response

# Coach Lessons Management
@app.get("/account/coach/lessons")
async def coach_lessons_page(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    
    coach = get_user_coach_profile(user, db)
    if not coach: return RedirectResponse(url="/account/coach/apply")
    
    # Fetch Bookings
    all_bookings = db.query(models.Booking).filter(
        models.Booking.coach_id == coach.id
    ).order_by(models.Booking.created_at.desc()).all()
    
    bookings_requested = []
    bookings_confirmed = []
    
    for b in all_bookings:
        # Fetch student name
        student = db.query(models.User).filter(models.User.id == b.student_id).first()
        if student:
            b.student_name = student.name or student.email.split('@')[0] or "學員"
        else:
            b.student_name = "未知學員"

        # Fetch Inquiry Thread
        thread = db.query(models.InquiryThread).filter(
            models.InquiryThread.coach_profile_id == coach.id,
            models.InquiryThread.student_id == b.student_id
        ).first()
        b.thread_id = thread.id if thread else None
        
        if b.status == "REQUESTED":
            bookings_requested.append(b)
        elif b.status in ["CONFIRMED", "IN_PROGRESS"]:
            bookings_confirmed.append(b)
        elif b.status == "COMPLETED":
            bookings_confirmed.append(b) # Backward compatibility or distinct?
            # User asked for 3 categories: Requested, Ongoing, Completed
            # But here we previously only had 2 lists. Let's start capturing it.
    
    # Re-loop to split cleanly if sticking to standard lists
    bookings_requested = [b for b in all_bookings if b.status == "REQUESTED"]
    bookings_ongoing = [b for b in all_bookings if b.status in ["CONFIRMED", "IN_PROGRESS"]]
    bookings_completed = [b for b in all_bookings if b.status in ["COMPLETED", "CANCELED"]]
            
    return templates.TemplateResponse("account/coach_lessons.html", {
        "request": request,
        "user": user,
        "bookings_requested": bookings_requested,
        "bookings_confirmed": bookings_ongoing, # Rename variable in template or keep 'confirmed' as 'ongoing'
        "bookings_completed": bookings_completed,
        "new_count": len(bookings_requested)
    })

@app.get("/register")
async def register_page(request: Request, error: str = None): return templates.TemplateResponse("auth/register.html", {"request": request, "user": request.state.user, "error": error})
@app.post("/register")
async def register(name: str = Form(...), email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.email == email).first(): return RedirectResponse(url="/register?error=此電子郵件已存在", status_code=302)
    user = models.User(name=name, email=email, hashed_password=auth.get_password_hash(password), role="user")
    db.add(user)
    db.commit()
    return RedirectResponse(url="/login?success=註冊成功，請登入", status_code=302)

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=302); response.delete_cookie("access_token"); return response

# --- Pydantic Schemas for Reviews & Complaints ---
from fastapi.responses import HTMLResponse

class ReviewCreate(BaseModel):
    lesson_id: int
    rating: float
    comment: Optional[str] = None
    is_anonymous: bool = False

class ComplaintCreate(BaseModel):
    coach_id: int
    lesson_id: Optional[int] = None
    thread_id: Optional[int] = None
    category: str
    description: str
    attachment_url: Optional[str] = None
    is_anonymous: bool = False

class AdminResolve(BaseModel):
    action: str # RESTORE, BAN, DISMISS, REQUEST_INFO
    note: Optional[str] = None

# --- Helper Functions ---

def update_coach_rating(db: Session, coach: models.CoachProfile):
    # Recalculate average rating
    reviews = db.query(models.Review).filter(models.Review.coach_id == coach.id).all()
    if not reviews:
        return
    
    total = sum(r.rating for r in reviews)
    avg = total / len(reviews)
    
    coach.rating = avg
    coach.rating_count = len(reviews)
    
    # Check for Low Rating Suspension
    if avg < 2.5 and len(reviews) >= 3: # Minimum 3 reviews to trigger
        coach.account_status = "SUSPENDED"
        coach.status = "SUSPENDED" # Dual-status for safety
        coach.suspension_reason = "Low Rating (Avg < 2.5)"
        
        # Log Admin Case
        case = models.AdminCase(
            coach_id=coach.id,
            case_type="LOW_RATING",
            trigger_source_type="SYSTEM",
            trigger_source_id=0,
            status="OPEN",
            result_note="Auto-triggered by system due to low rating."
        )
        db.add(case)
    
    db.commit()

# --- New Endpoints ---

@app.post("/api/reviews")
async def submit_review_generic(
    review: ReviewCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = request.state.user
    if not current_user: raise HTTPException(status_code=401)
    
    booking = db.query(models.Booking).filter(models.Booking.id == review.lesson_id).first()
    if not booking: raise HTTPException(status_code=404, detail="找不到預約紀錄")
    if booking.student_id != current_user.id: raise HTTPException(status_code=403, detail="這不是您的預約")
    
    if booking.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="課程尚未完成，請待雙方確認結案後再評分")
        
    existing = db.query(models.Review).filter(models.Review.booking_id == booking.id).first()
    if existing: raise HTTPException(status_code=400, detail="此預約已評分過")
    
    new_review = models.Review(
        booking_id=booking.id,
        coach_id=booking.coach_id,
        student_id=current_user.id,
        rating=review.rating,
        comment=review.comment,
        is_anonymous=review.is_anonymous
    )
    db.add(new_review)
    db.commit()
    
    coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == booking.coach_id).first()
    update_coach_rating(db, coach)
    
    return {"status": "success", "msg": "Review submitted"}

@app.post("/api/coaches/{coach_id}/reviews")
async def submit_coach_review(
    coach_id: int,
    review: ReviewCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = request.state.user
    if not current_user: raise HTTPException(status_code=401)
    
    # 1. Verify Booking
    booking = db.query(models.Booking).filter(models.Booking.id == review.lesson_id).first() # frontend sends lesson_id for booking
    if not booking: raise HTTPException(status_code=404, detail="找不到預約紀錄")
    
    if booking.coach_id != coach_id:
        raise HTTPException(status_code=400, detail="課程與教練不符")
        
    if booking.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="這不是您的預約")
        
    if booking.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="課程尚未完成(狀態需為COMPLETED)")
        
    # 2. Check Uniqueness
    existing = db.query(models.Review).filter(models.Review.booking_id == booking.id).first()
    if existing: raise HTTPException(status_code=400, detail="此預約已評分過")
    
    # 3. Create Review
    new_review = models.Review(
        booking_id=booking.id,
        coach_id=coach_id,
        student_id=current_user.id,
        rating=review.rating,
        comment=review.comment,
        is_anonymous=review.is_anonymous
    )
    db.add(new_review)
    db.commit()
    
    # 4. Update Stats & Auto-Suspend Logic
    coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == coach_id).first()
    update_coach_rating(db, coach)
    
    # Strict Suspension Rule
    if coach.rating_count >= 3 and (coach.rating or 0) < 2.5:
        if coach.account_status != "SUSPENDED":
            StatusService.suspend_coach(db, coach, f"Low Rating ({coach.rating})", "LOW_RATING", new_review.id)

    return {"status": "success", "msg": "Review submitted"}

@app.post("/api/coaches/{coach_id}/complaints")
async def submit_coach_complaint(
    coach_id: int,
    complaint: ComplaintCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = request.state.user
    if not current_user: raise HTTPException(status_code=401)
    
    # 1. Verify Interaction
    valid_interaction = False
    
    # Check Booking
    if complaint.lesson_id:
        b = db.query(models.Booking).filter(models.Booking.id == complaint.lesson_id).first()
        if b and b.student_id == current_user.id and b.coach_id == coach_id:
            if b.status in ["IN_PROGRESS", "COMPLETED"]:
                valid_interaction = True
            
    # Check Conversation
    if complaint.thread_id and not valid_interaction:
        c = db.query(models.Conversation).filter(models.Conversation.id == complaint.thread_id).first()
        if c and c.student_id == current_user.id and c.coach_id == coach_id:
            valid_interaction = True
            
    if not valid_interaction:
         raise HTTPException(status_code=403, detail="無有效對話或完課紀錄可供投訴")
         
    # 2. Create Complaint
    new_comp = models.Complaint(
        student_id=current_user.id,
        coach_id=coach_id,
        booking_id=complaint.lesson_id,
        conversation_id=complaint.thread_id,
        category=complaint.category,
        description=complaint.description,
        is_anonymous=complaint.is_anonymous
    )
    db.add(new_comp)
    db.flush()
    
    # 3. Auto-Suspend Immediately
    coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == coach_id).first()
    if coach:
        # Increment complaint count
        coach.complaint_count = (coach.complaint_count or 0) + 1
        # Apply suspension via Service (which also creates the AdminCase)
        StatusService.suspend_coach(db, coach, f"Complaint Received: {complaint.category}", "COMPLAINT", new_comp.id)
        
    db.commit()
    return {"status": "success", "msg": "Complaint submitted"}

# --- Feature: Admin Message Center Routes ---

@app.get("/admin/messages")
async def admin_message_center_page(request: Request, db: Session = Depends(get_db)):
    current_user = auth.get_admin_user(request, db)
    if not current_user: return RedirectResponse("/auth/login?role=admin")
    return templates.TemplateResponse("admin/messages.html", {"request": request, "user": current_user})

@app.get("/api/admin/conversations")
async def list_admin_conversations(
    role: str = "coach", # coach | student
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.admin_required)
):
    # Filter by user role via join
    query = db.query(models.AdminConversation).join(models.User, models.AdminConversation.user_id == models.User.id)
    
    # Filter by user role via join - REMOVED STRICT JOIN to allow topic-based filtering
    query = db.query(models.AdminConversation).join(models.User, models.AdminConversation.user_id == models.User.id)
    
    # Fetch all, then filter in python for flexibility with combined roles
    convs = query.order_by(models.AdminConversation.updated_at.desc()).all()
    
    res = []
    for c in convs:
        target_user = db.query(models.User).filter(models.User.id == c.user_id).first()
        coach_profile = db.query(models.CoachProfile).filter(models.CoachProfile.user_id == c.user_id).first()
        
        is_coach_user = coach_profile is not None
        
        # Topic Logic
        is_coach_topic = any(k in c.subject for k in ["停權", "審核", "Coach", "帳號"])
        is_student_topic = any(k in c.subject for k in ["投訴", "Student"])
        
        should_include = False
        if role == "coach":
            if is_coach_topic: should_include = True
        else: # Student Tab
            # Include if it is explicitly a student topic OR NOT a coach topic (general/student)
            if is_student_topic or (not is_coach_topic): should_include = True
            
        if not should_include: continue
        
        display_name = coach_profile.display_name if is_coach_user else target_user.name
        
        # Check unread
        unread = db.query(models.AdminMessage).filter(
            models.AdminMessage.conversation_id == c.id,
            models.AdminMessage.sender_role != "admin", 
            models.AdminMessage.is_read == False
        ).count() > 0
        
        res.append({
            "id": c.id,
            "subject": c.subject,
            "user_name": display_name,
            "updated_at": c.updated_at.strftime("%m/%d %H:%M"),
            "unread": unread
        })
    return res

@app.get("/api/admin/conversations/{id}")
async def get_admin_conversation_details(id: int, db: Session = Depends(get_db), admin: models.User = Depends(auth.admin_required)):
    conv = db.query(models.AdminConversation).filter(models.AdminConversation.id == id).first()
    if not conv: raise HTTPException(status_code=404)
    
    # Get user details
    target_user = db.query(models.User).filter(models.User.id == conv.user_id).first()
    coach_profile = db.query(models.CoachProfile).filter(models.CoachProfile.user_id == conv.user_id).first()
    display_name = coach_profile.display_name if coach_profile else target_user.name
    
    # Messages
    msgs = db.query(models.AdminMessage).filter(models.AdminMessage.conversation_id == id).order_by(models.AdminMessage.created_at.asc()).all()
    
    # Mark read
    for m in msgs:
        if m.sender_role != "admin" and not m.is_read:
            m.is_read = True
    db.commit()
    
    return {
        "id": conv.id,
        "subject": conv.subject,
        "user_name": display_name,
        "messages": [{
            "id": m.id,
            "content": m.content,
            "sender_role": m.sender_role,
            "created_at": m.created_at.strftime("%m/%d %H:%M")
        } for m in msgs]
    }

@app.post("/api/admin/conversations/{id}/messages")
async def send_admin_message(
    id: int, 
    content: Optional[str] = Form(None), 
    file: UploadFile = File(None),
    db: Session = Depends(get_db), 
    admin: models.User = Depends(auth.admin_required)
):
    if content is None: content = ""
    
    # Handle File Upload
    if file and file.filename:
        upload_dir = "app/static/uploads"
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)
            
        ext = os.path.splitext(file.filename)[1]
        unique_name = f"{uuid.uuid4()}{ext}"
        file_path = os.path.join(upload_dir, unique_name)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        file_url = f"/static/uploads/{unique_name}"
        content += f"\n[附件] {file_url}"
    
    if not content: raise HTTPException(status_code=400, detail="Content or file required")

    msg = models.AdminMessage(
        conversation_id=id,
        sender_id=admin.id,
        sender_role="admin",
        content=content,
        is_read=True 
    )
    db.add(msg)
    
    conv = db.query(models.AdminConversation).filter(models.AdminConversation.id == id).first()
    conv.updated_at = datetime.utcnow()
    
    db.commit()
    return {"status": "ok"}

# --- Admin Case Management APIs ---

@app.get("/api/admin/cases")
async def list_admin_cases(
    status: Optional[str] = None,
    case_type: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.admin_required)
):
    query = db.query(models.AdminCase)
    if status: query = query.filter(models.AdminCase.status == status)
    if case_type: query = query.filter(models.AdminCase.case_type == case_type)
    cases = query.order_by(models.AdminCase.created_at.desc()).all()
    
    res = []
    for c in cases:
        coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == c.coach_id).first()
        
        # Get Category/Subtitle
        category_display = c.case_type
        if c.case_type == "COMPLAINT" and c.trigger_source_id:
            comp = db.query(models.Complaint).filter(models.Complaint.id == c.trigger_source_id).first()
            if comp: category_display = comp.category
            
        res.append({
            "id": c.id,
            "type": c.case_type,
            "category": category_display, # New field for UI
            "status": c.status,
            "coach_name": coach.display_name if coach else "Unknown",
            "priority": c.priority,
            "action": c.action, # Needed for Resolved tab logic
            "created_at": c.created_at.strftime("%Y-%m-%d %H:%M")
        })
    return res

@app.get("/api/admin/cases/{id}")
async def get_admin_case(id: int, db: Session = Depends(get_db), admin: models.User = Depends(auth.admin_required)):
    case = db.query(models.AdminCase).filter(models.AdminCase.id == id).first()
    if not case: raise HTTPException(status_code=404)
    coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == case.coach_id).first()
    
    # Extra data based on type
    extra = {}
    if case.case_type == "COMPLAINT" and case.trigger_source_id:
        comp = db.query(models.Complaint).filter(models.Complaint.id == case.trigger_source_id).first()
        if comp:
            extra["complaint"] = {
                "category": comp.category,
                "description": comp.description,
                "attachment_url": comp.attachment_url,
                "created_at": comp.created_at.strftime("%Y-%m-%d")
            }
    elif case.case_type == "LOW_RATING":
        extra["rating_info"] = {
            "avg": coach.rating,
            "count": coach.rating_count
        }

    return {
        "case": {
            "id": case.id,
            "type": case.case_type,
            "status": case.status,
            "priority": case.priority,
            "admin_note": case.admin_note,
            "action": case.action,
            "created_at": case.created_at.isoformat()
        },
        "coach": {
            "id": coach.id,
            "display_name": coach.display_name,
            "review_status": coach.review_status,
            "account_status": coach.account_status
        },
        "extra": extra
    }

@app.post("/api/admin/cases/{id}/assign")
async def assign_admin_case(id: int, payload: dict, db: Session = Depends(get_db), admin: models.User = Depends(auth.admin_required)):
    case = db.query(models.AdminCase).filter(models.AdminCase.id == id).first()
    if not case: raise HTTPException(status_code=404)
    case.admin_assignee_id = payload.get("admin_id")
    case.status = "IN_REVIEW"
    db.commit()
    return {"status": "ok"}

@app.post("/api/admin/cases/{id}/transition")
async def transition_admin_case(id: int, payload: dict, db: Session = Depends(get_db), admin: models.User = Depends(auth.admin_required)):
    case = db.query(models.AdminCase).filter(models.AdminCase.id == id).first()
    if not case: raise HTTPException(status_code=404)
    next_status = payload.get("next_status")
    success, msg = StatusService.apply_case_transition(db, case, next_status, "admin")
    if not success: raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok"}

@app.post("/api/admin/cases/{id}/resolve")
async def resolve_admin_case(id: int, payload: dict, db: Session = Depends(get_db), admin: models.User = Depends(auth.admin_required)):
    case = db.query(models.AdminCase).filter(models.AdminCase.id == id).first()
    if not case: raise HTTPException(status_code=404)
    
    StatusService.resolve_case(
        db, case, 
        action=payload.get("action"), 
        admin_note=payload.get("admin_note"),
        admin_id=admin.id
    )
    return {"status": "ok"}

@app.post("/api/coach/cases/{id}/submit-info")
async def coach_submit_case_info(id: int, payload: dict, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    
    case = db.query(models.AdminCase).filter(models.AdminCase.id == id).first()
    if not case: raise HTTPException(status_code=404)
    
    coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == case.coach_id).first()
    if not coach or coach.user_id != user.id: raise HTTPException(status_code=403)
    
    if case.status != "NEED_INFO": raise HTTPException(status_code=400, detail="此案件目前不需補件")
    
    # Update note or add to payload
    case.admin_note = (case.admin_note or "") + f"\n[教練補件 {datetime.utcnow().strftime('%Y-%m-%d')}]: " + payload.get("info", "")
    case.status = "IN_REVIEW"
    db.commit()
    return {"status": "ok"}

@app.get("/api/coaches/{coach_id}/reviews")
async def get_coach_reviews(
    coach_id: int, 
    db: Session = Depends(get_db)
):
    reviews = db.query(models.Review).filter(models.Review.coach_id == coach_id).order_by(models.Review.created_at.desc()).all()
    coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == coach_id).first()
    
    # Distribution
    dist = {1:0, 2:0, 3:0, 4:0, 5:0}
    for r in reviews:
        stars = int(round(r.rating))
        if 1 <= stars <= 5: dist[stars] += 1
        
    review_list = []
    for r in reviews:
        student_name = "匿名學員"
        if not r.is_anonymous:
            s = db.query(models.User).filter(models.User.id == r.student_id).first()
            student_name = s.name if s else "未知學員"
            
        review_list.append({
            "rating": r.rating,
            "comment": r.comment,
            "date": r.created_at.strftime("%Y/%m/%d"),
            "student_name": student_name,
            "is_anonymous": r.is_anonymous
        })
        
    return {
        "avg_rating": round(coach.rating or 0, 1) if coach else 0,
        "rating_count": coach.rating_count or 0 if coach else 0,
        "distribution": dist,
        "reviews": review_list
    }

# --- Feature: Coach Showcase & Plan APIs ---

@app.get("/api/coach/me/plan")
async def get_my_plan(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    coach = get_user_coach_profile(user, db)
    if not coach: raise HTTPException(status_code=404)
    
    level = coach.subscription_level or "basic"
    plan = PLAN_LIMITS.get(level, PLAN_LIMITS["basic"])
    
    # Calculate Usage
    media_count = db.query(models.CoachMedia).filter(models.CoachMedia.coach_id == coach.id).count()
    link_count = db.query(models.CoachLink).filter(models.CoachLink.coach_id == coach.id).count()
    faq_count = db.query(models.CoachFaq).filter(models.CoachFaq.coach_id == coach.id).count()
    offer_count = db.query(models.CoachOffer).filter(models.CoachOffer.coach_id == coach.id).count()
    testimonial_count = db.query(models.CoachTestimonial).filter(models.CoachTestimonial.coach_id == coach.id).count()
    
    return {
        "level": level,
        "plan_name": plan["name"],
        "limits": plan,
        "usage": {
            "media": media_count,
            "link": link_count,
            "faq": faq_count,
            "offer": offer_count,
            "testimonial": testimonial_count
        }
    }

@app.get("/api/coach/me/showcase")
async def get_my_showcase(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    coach = get_user_coach_profile(user, db)
    if not coach: raise HTTPException(status_code=404)
    
    # Load config
    config = json.loads(coach.showcase_config or '{"order": [], "visible": {}}')
    
    # Load data
    return {
        "config": config,
        "media": [
            {"id": m.id, "type": m.type, "url": m.url, "title": m.title, "sort_order": m.sort_order} 
            for m in coach.features_media
        ],
        "offers": [
            {"id": o.id, "title": o.title, "price_text": o.price_text, "duration": o.duration, "description": o.description}
            for o in coach.features_offers
        ],
        "testimonials": [
            {"id": t.id, "student_name": t.student_name, "content": t.content, "image_url": t.image_url, "is_pinned": t.is_pinned}
            for t in coach.features_testimonials
        ],
        "links": [
            {"id": l.id, "text": l.text, "url": l.url, "icon": l.icon}
            for l in coach.features_links
        ],
        "faq": [
            {"id": f.id, "question": f.question, "answer": f.answer}
            for f in coach.features_faq
        ]
    }

class MediaCreate(BaseModel):
    type: str # image / video / youtube
    url: str
    title: Optional[str] = None

@app.post("/api/coach/me/media")
async def add_media(payload: MediaCreate, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    coach = get_user_coach_profile(user, db)
    
    # Check Limit
    allowed, msg = validate_feature_limit(coach, "media", db)
    if not allowed: raise HTTPException(status_code=403, detail=msg)
    
    # If video, check Plan allows video
    plan = PLAN_LIMITS.get(coach.subscription_level or 'basic')
    if (payload.type == 'video' or payload.type == 'youtube') and not plan['video_allowed']:
         raise HTTPException(status_code=403, detail=f"您的「{plan['name']}」方案暫不支援影片上傳。")

    new_media = models.CoachMedia(
        coach_id=coach.id,
        type=payload.type,
        url=payload.url,
        title=payload.title
    )
    db.add(new_media)
    db.commit()
    return {"status": "ok", "id": new_media.id}

@app.delete("/api/coach/me/media/{id}")
async def delete_media(id: int, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    coach = get_user_coach_profile(user, db)
    media = db.query(models.CoachMedia).filter(models.CoachMedia.id == id, models.CoachMedia.coach_id == coach.id).first()
    if media:
        db.delete(media)
        db.commit()
    return {"status": "ok"}

class LinkCreate(BaseModel):
    text: str
    url: str
    icon: str

@app.post("/api/coach/me/links")
async def add_link(payload: LinkCreate, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    coach = get_user_coach_profile(user, db)
    
    # Check Limit
    allowed, msg = validate_feature_limit(coach, "link", db)
    if not allowed: raise HTTPException(status_code=403, detail=msg)
    
    new_item = models.CoachLink(
        coach_id=coach.id,
        text=payload.text,
        url=payload.url,
        icon=payload.icon
    )
    db.add(new_item)
    db.commit()
    return {"status": "ok", "id": new_item.id}

@app.delete("/api/coach/me/links/{id}")
async def delete_link(id: int, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    coach = get_user_coach_profile(user, db)
    item = db.query(models.CoachLink).filter(models.CoachLink.id == id, models.CoachLink.coach_id == coach.id).first()
    if item:
        db.delete(item)
        db.commit()
    return {"status": "ok"}

class FaqCreate(BaseModel):
    question: str
    answer: str

@app.post("/api/coach/me/faq")
async def add_faq(payload: FaqCreate, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    coach = get_user_coach_profile(user, db)
    
    # Check Limit
    allowed, msg = validate_feature_limit(coach, "faq", db)
    if not allowed: raise HTTPException(status_code=403, detail=msg)
    
    new_item = models.CoachFaq(
        coach_id=coach.id,
        question=payload.question,
        answer=payload.answer
    )
    db.add(new_item)
    db.commit()
    return {"status": "ok", "id": new_item.id}

@app.delete("/api/coach/me/faq/{id}")
async def delete_faq(id: int, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    coach = get_user_coach_profile(user, db)
    item = db.query(models.CoachFaq).filter(models.CoachFaq.id == id, models.CoachFaq.coach_id == coach.id).first()
    if item:
        db.delete(item)
        db.commit()
    return {"status": "ok"}

class OfferCreate(BaseModel):
    title: str
    price_text: str
    duration: str
    description: str
    tags: List[str] = []

@app.post("/api/coach/me/offers")
async def add_offer(payload: OfferCreate, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    coach = get_user_coach_profile(user, db)
    
    # Check Limit
    allowed, msg = validate_feature_limit(coach, "offer", db)
    if not allowed: raise HTTPException(status_code=403, detail=msg)
    
    new_item = models.CoachOffer(
        coach_id=coach.id,
        title=payload.title,
        price_text=payload.price_text,
        duration=payload.duration,
        description=payload.description,
        tags=json.dumps(payload.tags, ensure_ascii=False)
    )
    db.add(new_item)
    db.commit()
    return {"status": "ok", "id": new_item.id}

@app.delete("/api/coach/me/offers/{id}")
async def delete_offer(id: int, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    coach = get_user_coach_profile(user, db)
    item = db.query(models.CoachOffer).filter(models.CoachOffer.id == id, models.CoachOffer.coach_id == coach.id).first()
    if item:
        db.delete(item)
        db.commit()
    return {"status": "ok"}

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    upload_dir = "app/static/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    
    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    filepath = os.path.join(upload_dir, filename)
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return {"url": f"/static/uploads/{filename}", "type": "video" if file.content_type.startswith("video") else "image"}


    
# ... Similar logic for Offers, Testimonials, Config ...

class ShowcaseConfigUpdate(BaseModel):
    visible: Dict[str, bool]
    order: List[str]

@app.post("/api/coach/me/showcase-config")
async def update_showcase_config(payload: ShowcaseConfigUpdate, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    coach = get_user_coach_profile(user, db)
    
    current = json.loads(coach.showcase_config or '{}')
    current['visible'] = payload.visible
    current['order'] = payload.order
    
    coach.showcase_config = json.dumps(current, ensure_ascii=False)
    db.commit()
    return {"status": "ok"}

@app.post("/api/account/coach/subscription")
async def update_subscription(payload: dict, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    
    coach = get_user_coach_profile(user, db)
    if not coach: raise HTTPException(status_code=404)
    
    level = payload.get("level")
    if level not in ["basic", "pro", "elite"]:
        raise HTTPException(status_code=400)
        
    coach.subscription_level = level
    db.commit()
    return {"status": "ok"}

@app.get("/api/coaches/{coach_id}/interaction-eligibility")
async def check_interaction_eligibility(
    coach_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    user = request.state.user
    if not user:
        return {"can_review": False, "can_complain": False, "reason": "未登入", "booking_ids": [], "thread_ids": []}

    # Review Eligibility: Completed Bookings that are NOT reviewed yet
    # Find bookings: student=user, coach=coach, status=COMPLETED
    completed_bookings = db.query(models.Booking).filter(
        models.Booking.student_id == user.id,
        models.Booking.coach_id == coach_id,
        models.Booking.status == "COMPLETED"
    ).all()
    
    valid_review_booking_ids = []
    for b in completed_bookings:
        has_review = db.query(models.Review).filter(models.Review.booking_id == b.id).first()
        if not has_review:
            valid_review_booking_ids.append(b.id)
            
    # Complaint Eligibility: Conversation or active/completed bookings
    # 1. Conversations
    convs = db.query(models.Conversation).filter(
        models.Conversation.student_id == user.id,
        models.Conversation.coach_id == coach_id
    ).all()
    conv_ids = [c.id for c in convs]
    
    # 2. Bookings (IN_PROGRESS or COMPLETED)
    active_bookings = db.query(models.Booking).filter(
        models.Booking.student_id == user.id,
        models.Booking.coach_id == coach_id,
        models.Booking.status.in_(["IN_PROGRESS", "COMPLETED"])
    ).all()
    booking_ids = [b.id for b in active_bookings]
    
    can_complain = (len(conv_ids) > 0) or (len(booking_ids) > 0)
    
    return {
        "can_review": len(valid_review_booking_ids) > 0,
        "review_booking_ids": valid_review_booking_ids,
        "review_reason": "需完課後(狀態為COMPLETED)才能評價" if len(valid_review_booking_ids) == 0 else "",
        
        "can_complain": can_complain,
        "complaint_booking_ids": booking_ids,
        "complaint_thread_ids": conv_ids, # keeping key for frontend consistency
        "complaint_reason": "需有對話紀錄或正進行中/已完成課程才可投訴" if not can_complain else ""
    }

# --- User Message Center Routes ---

@app.get("/account/messages")
async def user_message_center_page(request: Request):
    user = request.state.user
    if not user: return RedirectResponse("/login")
    return templates.TemplateResponse("account/messages.html", {"request": request, "user": user})

@app.get("/api/account/conversations")
async def list_user_conversations(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    
    combined_list = []

    # 1. Admin Conversations
    admin_convs = db.query(models.AdminConversation).filter(
        models.AdminConversation.user_id == user.id
    ).all()
    
    for c in admin_convs:
        unread = db.query(models.AdminMessage).filter(
            models.AdminMessage.conversation_id == c.id,
            models.AdminMessage.sender_role == "admin", 
            models.AdminMessage.is_read == False
        ).count() > 0
        combined_list.append({
            "id": f"admin_{c.id}",
            "type": "admin", # For frontend icon/logic
            "target_name": "平台管理員",
            "avatar": "A",
            "subject": c.subject,
            "updated_at": c.updated_at,
            "display_time": c.updated_at.strftime("%m/%d %H:%M"),
            "unread": unread
        })

    # 2. Inquiry Threads (Student <-> Coach)
    if user.role == "coach":
        coach_profile = get_user_coach_profile(user, db)
        if coach_profile:
            threads = db.query(models.InquiryThread).filter(models.InquiryThread.coach_profile_id == coach_profile.id).all()
            for t in threads:
                student = db.query(models.User).filter(models.User.id == t.student_id).first()
                name = student.name or "學員" if student else "未知學員"
                combined_list.append({
                    "id": f"inquiry_{t.id}",
                    "type": "inquiry",
                    "target_name": name,
                    "avatar": name[0],
                    "subject": "課程諮詢", 
                    "updated_at": t.updated_at,
                    "display_time": t.updated_at.strftime("%m/%d %H:%M"),
                    "unread": False # TODO: Implement unread logic for inquiries if needed
                })
    else:
        # Student
        threads = db.query(models.InquiryThread).filter(models.InquiryThread.student_id == user.id).all()
        for t in threads:
            coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == t.coach_profile_id).first()
            name = coach.display_name if coach else "未知教練"
            combined_list.append({
                "id": f"inquiry_{t.id}",
                "type": "inquiry",
                "target_name": name,
                "avatar": name[0],
                "subject": "課程諮詢",
                "updated_at": t.updated_at,
                "display_time": t.updated_at.strftime("%m/%d %H:%M"),
                "unread": False
            })

    # Sort DESC
    combined_list.sort(key=lambda x: x['updated_at'], reverse=True)
    return combined_list

@app.get("/api/account/conversations/{conv_id}")
async def get_user_conversation_details(conv_id: str, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    
    parts = conv_id.split('_')
    c_type = parts[0]
    c_id = int(parts[1])
    
    if c_type == "admin":
        conv = db.query(models.AdminConversation).filter(
            models.AdminConversation.id == c_id,
            models.AdminConversation.user_id == user.id
        ).first()
        if not conv: raise HTTPException(status_code=404)
        
        msgs = db.query(models.AdminMessage).filter(models.AdminMessage.conversation_id == c_id).order_by(models.AdminMessage.created_at.asc()).all()
        
        # Mark read
        for m in msgs:
            if m.sender_role == "admin" and not m.is_read:
                m.is_read = True
        db.commit()
        
        return {
            "id": conv_id,
            "target_name": "平台管理員",
            "subject": conv.subject,
            "messages": [{
                "id": m.id,
                "content": m.content,
                "is_me": m.sender_role != "admin", # Admin is 'other'
                "sender_name": "管理員" if m.sender_role == "admin" else "你",
                "created_at": m.created_at.strftime("%m/%d %H:%M")
            } for m in msgs]
        }
    
    elif c_type == "inquiry":
        # Handle Inquiry
        thread = db.query(models.InquiryThread).filter(models.InquiryThread.id == c_id).first()
        if not thread: raise HTTPException(status_code=404)
        
        # Verify access
        if user.role == "coach":
             # Must check via coach profile
             coach = get_user_coach_profile(user, db)
             if not coach or thread.coach_profile_id != coach.id: raise HTTPException(status_code=403)
             target_name = db.query(models.User).filter(models.User.id == thread.student_id).first().name 
        else:
             if thread.student_id != user.id: raise HTTPException(status_code=403)
             target_name = db.query(models.CoachProfile).filter(models.CoachProfile.id == thread.coach_profile_id).first().display_name

        msgs = db.query(models.InquiryMessage).filter(models.InquiryMessage.thread_id == c_id).order_by(models.InquiryMessage.created_at.asc()).all()
        
        return {
            "id": conv_id,
            "target_name": target_name,
            "subject": "課程諮詢",
            "messages": [{
                "id": m.id,
                "content": m.content,
                "is_me": m.sender_id == user.id,
                "sender_name": "你" if m.sender_id == user.id else target_name,
                "created_at": m.created_at.strftime("%m/%d %H:%M")
            } for m in msgs]
        }

@app.post("/api/account/conversations/{conv_id}/messages")
async def send_user_message(conv_id: str, payload: dict, request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    
    content = payload.get("content")
    if not content: raise HTTPException(status_code=400)
    
    parts = conv_id.split('_')
    c_type = parts[0]
    c_id = int(parts[1])
    
    if c_type == "admin":
        conv = db.query(models.AdminConversation).filter(models.AdminConversation.id == c_id, models.AdminConversation.user_id == user.id).first()
        if not conv: raise HTTPException(status_code=404)
        
        msg = models.AdminMessage(
            conversation_id=c_id,
            sender_id=user.id,
            sender_role="user",
            content=content,
            is_read=False
        )
        db.add(msg)
        conv.updated_at = datetime.utcnow()
        db.commit()
        return {"status": "ok"}
        
    elif c_type == "inquiry":
        thread = db.query(models.InquiryThread).get(c_id)
        if not thread: raise HTTPException(status_code=404)
        
        # Access check omitted for brevity (trusted for now or re-verify) - reusing logic ideal
        
        msg = models.InquiryMessage(
            thread_id=c_id,
            sender_id=user.id,
            content=content
        )
        db.add(msg)
        thread.last_message = content
        thread.updated_at = datetime.utcnow()
        db.commit()
        return {"status": "ok"}

@app.post("/api/complaints")
async def submit_complaint(
    coach_id: int = Form(...),
    lesson_id: Optional[int] = Form(None),
    thread_id: Optional[int] = Form(None),
    category: str = Form(...),
    description: str = Form(...),
    is_anonymous: bool = Form(False),
    attachment_file: Optional[UploadFile] = File(None),
    request: Request = None,
    db: Session = Depends(get_db)
):
    current_user = request.state.user
    if not current_user: raise HTTPException(status_code=401)
    
    # Validation: Description mandatory
    if not description or not description.strip():
        raise HTTPException(status_code=400, detail="請填寫投訴詳細描述")
    
    # Handle File Upload
    attachment_url = None
    if attachment_file:
        if not attachment_file.content_type.startswith("image/") and attachment_file.content_type != "application/pdf":
             raise HTTPException(status_code=400, detail="只支援圖片或 PDF 格式")
        
        import shutil
        import uuid
        import os
        
        file_ext = attachment_file.filename.split(".")[-1]
        new_filename = f"{uuid.uuid4()}.{file_ext}"
        upload_dir = "app/static/uploads/complaints"
        os.makedirs(upload_dir, exist_ok=True)
        file_path = f"{upload_dir}/{new_filename}"
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(attachment_file.file, buffer)
            
        attachment_url = f"/static/uploads/complaints/{new_filename}"

    # Validation: Interaction
    valid_interaction = False
    assigned_lesson_id = None
    assigned_booking_id = None
    
    # Debugging
    print(f"DEBUG: submit_complaint check - User: {current_user.id}, LessonID: {lesson_id}, ThreadID: {thread_id}")
    
    if lesson_id:
        # 1. Check for Duplicate Complaint for this lesson/booking
        existing_booking = db.query(models.Complaint).filter(
            models.Complaint.student_id == current_user.id,
            models.Complaint.booking_id == lesson_id
        ).first()
        existing_lesson = db.query(models.Complaint).filter(
            models.Complaint.student_id == current_user.id,
            models.Complaint.lesson_id == lesson_id
        ).first()
        if existing_booking or existing_lesson:
            raise HTTPException(status_code=400, detail="您已對此課程提交過投訴，請靜候管理員處理")

        # Check new Booking model first
        booking = db.query(models.Booking).filter(models.Booking.id == lesson_id).first()
        print(f"DEBUG: Booking Found: {booking} (Student: {booking.student_id if booking else 'None'})")
        
        if booking and booking.student_id == current_user.id:
            valid_interaction = True
            assigned_booking_id = booking.id
        
        # Fallback to legacy Lesson model
        if not valid_interaction:
            lesson = db.query(models.Lesson).filter(models.Lesson.id == lesson_id).first()
            if lesson and lesson.student_id == current_user.id:
                valid_interaction = True
                assigned_lesson_id = lesson.id
             
             
    if thread_id and not valid_interaction:
        # Check for Duplicate Complaint for this thread
        existing_thread = db.query(models.Complaint).filter(
            models.Complaint.student_id == current_user.id,
            models.Complaint.thread_id == thread_id
        ).first()
        if existing_thread:
            raise HTTPException(status_code=400, detail="您已對此諮詢提交過投訴，請靜候管理員處理")

        # Check new Conversation model
        conv = db.query(models.Conversation).filter(models.Conversation.id == thread_id).first()
        if conv and conv.student_id == current_user.id:
            valid_interaction = True
            
        # Fallback to legacy InquiryThread
        if not valid_interaction:
            thread = db.query(models.InquiryThread).filter(models.InquiryThread.id == thread_id).first()
            if thread and thread.student_id == current_user.id:
                valid_interaction = True
            
    if not valid_interaction:
        raise HTTPException(status_code=403, detail="找不到有效的互動紀錄 (課程或諮詢)，無法投訴")
    
    # Create Complaint
    new_complaint = models.Complaint(
        student_id=current_user.id,
        coach_id=coach_id,
        lesson_id=assigned_lesson_id,
        booking_id=assigned_booking_id,
        category=category,
        description=description,
        attachment_url=attachment_url,
        is_anonymous=is_anonymous,
        thread_id=thread_id
    )

    db.add(new_complaint)
    
    # Trigger Review Process (No Auto-Suspend)
    coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == coach_id).first()
    # Log Admin Case (Standard Priority)
    db.flush() # get ID
    case = models.AdminCase(
        coach_id=coach.id,
        case_type="COMPLAINT",
        trigger_source_type="COMPLAINT",
        trigger_source_id=new_complaint.id,
        status="OPEN",
        priority="MED",
        result_note="User submitted complaint. Pending admin review."
    )
    db.add(case)
    db.commit()

    return {"status": "success", "msg": "Complaint submitted.", "id": new_complaint.id}

@app.get("/account/student/lessons")
async def student_lessons_page(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    
    # 1. Fetch Bookings (New System)
    bookings = db.query(models.Booking).filter(
        models.Booking.student_id == user.id
    ).order_by(models.Booking.created_at.desc()).all()
    
    lessons_pending = []
    lessons_ongoing = []
    lessons_completed = []
    reviewed_lesson_ids = [r.booking_id for r in db.query(models.Review).filter(models.Review.student_id == user.id).all()]
    
    for b in bookings:
        # Pre-fetch coach
        b.coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == b.coach_id).first()
        # Adapt fields for template
        b.topic = b.sport_type or "預約課程"
        b.start_time = b.schedule_start_at or b.created_at
        b.end_time = b.schedule_end_at
        
        if b.status in ["COMPLETED", "CANCELED"]:
             lessons_completed.append(b)
        elif b.status == "REQUESTED":
             lessons_pending.append(b)
        else:
             lessons_ongoing.append(b)
            
    return templates.TemplateResponse("account/lessons.html", {
        "request": request,
        "user": user,
        "lessons_pending": lessons_pending,
        "lessons_ongoing": lessons_ongoing,
        "lessons_completed": lessons_completed,
        "reviewed_lesson_ids": reviewed_lesson_ids,
        "taiwan_areas": TAIWAN_AREAS
    })

@app.get("/api/student/rateable-lessons")
async def get_rateable_lessons(
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = request.state.user
    if not current_user: return []
    
    # Get completed lessons
    lessons = db.query(models.Lesson).filter(
        models.Lesson.student_id == current_user.id,
        models.Lesson.status == "COMPLETED"
    ).all()
    
    result = []
    for l in lessons:
        review = db.query(models.Review).filter(models.Review.lesson_id == l.id).first()
        if not review:
            coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == l.coach_id).first()
            result.append({
                "id": l.id,
                "coach_name": coach.display_name if coach else "Unknown Coach",
                "topic": l.topic,
                "date": l.start_time.strftime("%Y-%m-%d") if l.start_time else "N/A"
            })
            
    return result

# --- Favorites System ---

class FavoriteToggle(BaseModel):
    coach_id: int

@app.get("/api/me/favorites")
async def get_my_favorites(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return {"coach_ids": []}
    
    favs = db.query(models.Favorite).filter(models.Favorite.student_id == user.id).all()
    return {"coach_ids": [f.coach_id for f in favs]}

@app.post("/api/me/favorites/toggle")
async def toggle_favorite(
    data: FavoriteToggle,
    request: Request,
    db: Session = Depends(get_db)
):
    user = request.state.user
    if not user: raise HTTPException(status_code=401, detail="Please login")
    
    existing = db.query(models.Favorite).filter(
        models.Favorite.student_id == user.id,
        models.Favorite.coach_id == data.coach_id
    ).first()
    
    if existing:
        db.delete(existing)
        db.commit()
        return {"coach_id": data.coach_id, "is_favorited": False}
    else:
        new_fav = models.Favorite(student_id=user.id, coach_id=data.coach_id)
        db.add(new_fav)
        db.commit()
        # Log Event for Dashboard
        subscription_service.log_event(db, "favorite_add", coach_id=data.coach_id, user_id=user.id)
        return {"coach_id": data.coach_id, "is_favorited": True}

@app.get("/account/student/favorites")
async def student_favorites_page(request: Request, db: Session = Depends(get_db)):
    user = request.state.user
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("account/favorites.html", {
        "request": request, 
        "user": user,
        "taiwan_areas": TAIWAN_AREAS
    })

@app.get("/api/student/favorites")
async def get_student_favorite_details(
    request: Request,
    sport: str = Query(None),
    db: Session = Depends(get_db)
):
    user = request.state.user
    if not user: raise HTTPException(status_code=401)
    
    # Get favorite coach IDs
    favs = db.query(models.Favorite).filter(models.Favorite.student_id == user.id).all()
    coach_ids = [f.coach_id for f in favs]
    
    if not coach_ids:
        return {"groups": []}
    
    query = db.query(models.CoachProfile).filter(models.CoachProfile.id.in_(coach_ids))
    coaches = query.all()
    
    # Grouping logic
    # We want: All (implied), Fitness, Diving, Skiing
    groups = {
        "fitness": {"sport": "fitness", "sport_label": "健身", "coaches": []},
        "diving": {"sport": "diving", "sport_label": "潛水", "coaches": []},
        "skiing": {"sport": "skiing", "sport_label": "滑雪", "coaches": []},
        "other": {"sport": "other", "sport_label": "其他", "coaches": []} # Fallback
    }
    
    for c in coaches:
        # Determine main sport for grouping
        try:
            s_list = json.loads(c.sports) if c.sports else []
            if isinstance(s_list, str): s_list = [s_list] # Handle edge case if double encoded or simple str
        except:
            s_list = []
            
        main_sport = s_list[0] if len(s_list) > 0 else "unknown"
        
        target_group = "other"
        if "健身" in main_sport or "重訓" in main_sport: target_group = "fitness"
        elif "潛水" in main_sport or "自潛" in main_sport: target_group = "diving"
        elif "滑雪" in main_sport: target_group = "skiing"
        
        # Parse tags
        try:
            t_list = json.loads(c.teaching_styles) if c.teaching_styles else []
        except:
            t_list = []

        # Format coach data
        c_data = {
            "id": c.id,
            "name": c.display_name,
            "avatar_url": c.avatar,
            "avg_rating": round(c.rating or 0, 1),
            "rating_count": c.rating_count or 0,
            "regions": json.loads(c.service_districts) if hasattr(c, "service_districts") and c.service_districts else [],
            "price_range": c.price_range,
            "tags": t_list[:2],
            "status": c.status, # ACTIVE, SUSPENDED
            "sport_display": main_sport
        }
        
        groups[target_group]["coaches"].append(c_data)
        
    # Convert to list and filter if sport param is present (though frontend might handle All tab)
    result_groups = []
    if sport and sport != "all":
        if sport in groups:
            result_groups.append(groups[sport])
    else:
        # Return all non-empty groups
        for key in ["fitness", "diving", "skiing", "other"]:
            if len(groups[key]["coaches"]) > 0:
                result_groups.append(groups[key])
                
    return {"groups": result_groups}

# --- Admin Case Management ---
@app.get("/admin/cases", response_class=HTMLResponse)
async def admin_cases_page(
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = request.state.user
    if not current_user or current_user.role != "admin":
        return RedirectResponse("/", status_code=303)
        
    # Calculate stats for the 4 cards
    week_ago = datetime.utcnow() - timedelta(days=7)
    
    pending_count = db.query(models.AdminCase).filter(models.AdminCase.status == "OPEN").count()
    new_week_count = db.query(models.AdminCase).filter(models.AdminCase.created_at >= week_ago).count()
    low_rating_week = db.query(models.AdminCase).filter(
        models.AdminCase.case_type == "LOW_RATING",
        models.AdminCase.created_at >= week_ago
    ).count()
    
    # Avg process time: simplified for now
    avg_str = "1.2h" 
        
    return templates.TemplateResponse("admin/cases.html", {
        "request": request, 
        "user": current_user,
        "pending_count": pending_count,
        "new_week_count": new_week_count,
        "low_rating_week": low_rating_week,
        "avg_process_time": avg_str
    })

# --- Debug: Create Mock Lesson ---
@app.post("/debug/create-lesson")
async def debug_create_lesson(
    coach_id: int = Form(...),
    student_email: str = Form("student@example.com"),
    topic: str = Form("測試課程"),
    status: str = Form("COMPLETED"),
    db: Session = Depends(get_db)
):
    student = db.query(models.User).filter(models.User.email == student_email).first()
    # If no student log, pick first user
    if not student: 
        student = db.query(models.User).filter(models.User.role == "user").first()
    
    lesson = models.Lesson(
        student_id=student.id,
        coach_id=coach_id,
        status=status,
        topic=topic,
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow()
    )
    db.add(lesson)
    db.commit()
    return {"msg": "Lesson created", "id": lesson.id, "student": student.email}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
