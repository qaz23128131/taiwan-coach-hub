from sqlalchemy import Column, Integer, String, Boolean, Text, ForeignKey, DateTime, Float, JSON, UniqueConstraint, Date
from sqlalchemy.orm import relationship
from .database import Base
from datetime import datetime

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    name = Column(String)
    phone = Column(String)
    avatar_url = Column(String)
    role = Column(String, default="user") # user, admin
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class CoachProfile(Base):
    __tablename__ = "coach_profiles"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    display_name = Column(String)
    avatar = Column(String, default="/static/default_avatar.png")
    bio = Column(Text)
    
    # --- State Machine Fields ---
    review_status = Column(String, default="DRAFT")       # DRAFT / PENDING_REVIEW / APPROVED / REJECTED
    visibility_status = Column(String, default="HIDDEN")   # HIDDEN / VISIBLE
    account_status = Column(String, default="ACTIVE")      # ACTIVE / SUSPENDED
    is_banned = Column(Boolean, default=False)             # BAN logic
    
    # 狀態管理: DRAFT | PENDING | APPROVED | REJECTED
    status = Column(String, default="DRAFT") 
    submit_type = Column(String, default="NEW") # NEW | UPDATE
    reject_reason = Column(Text) # Overall note
    reject_reasons_json = Column(Text, default="[]") # Template keys: ["avatar_invalid", ...]
    review_note = Column(Text)
    submitted_at = Column(DateTime)
    approved_at = Column(DateTime)
    reviewed_at = Column(DateTime)
    reviewed_by_id = Column(Integer, ForeignKey("users.id"))
    is_verified = Column(Boolean, default=False)

    # 核心區域與運動資訊
    service_all_areas = Column(Boolean, default=False)
    service_cities = Column(Text, default="[]") 
    service_districts = Column(Text, default="[]") 
    sports = Column(Text, default="[]") 
    
    # --- 新增配對與進階欄位 ---
    service_mode = Column(String, default="flexible")
    tags = Column(Text, default="[]") 
    
    # 共用進階欄位
    teaching_styles = Column(Text, default="[]")
    audiences = Column(Text, default="[]")
    venues = Column(Text, default="[]")
    
    # 運動專屬欄位 (以 JSON 字串儲存)
    specialties = Column(Text, default="[]")
    gear_type = Column(String)
    other_specialty = Column(String)
    
    rating = Column(Float, default=4.8)
    price_min = Column(Integer, default=1000)
    price_max = Column(Integer, default=3000)
    price_per_session = Column(Integer)
    price_range = Column(String)
    last_updated = Column(DateTime, default=datetime.utcnow)

    # 其他元資料
    availability = Column(Text, default="[]")
    class_types = Column(Text, default="[]")
    
    subscription_level = Column(String, default="free") 
    lead_count = Column(Integer, default=0)
    view_count = Column(Integer, default=0)
    rating_count = Column(Integer, default=0)
    approved_profile = Column(Text, default="{}") 
    pending_profile = Column(Text, default="{}") 
    
    # 停權與風險管理
    # 停權與風險管理
    suspension_reason = Column(Text) # "Low Rating" | "Complaint: abuse"
    complaint_count = Column(Integer, default=0)

    # [方案訂閱 & 展示頁設定]
    # subscription_level default: 'basic' (was 'free')
    subscription_expire_at = Column(DateTime, nullable=True)
    showcase_config = Column(String, default='{"order": [], "visible": {}}')
    
    # [關聯]
    features_media = relationship("CoachMedia", back_populates="coach", cascade="all, delete-orphan")
    features_links = relationship("CoachLink", back_populates="coach", cascade="all, delete-orphan")
    features_faq = relationship("CoachFaq", back_populates="coach", cascade="all, delete-orphan")
    features_offers = relationship("CoachOffer", back_populates="coach", cascade="all, delete-orphan")
    features_testimonials = relationship("CoachTestimonial", back_populates="coach", cascade="all, delete-orphan")
    daily_metrics = relationship("CoachDailyMetric", back_populates="coach", cascade="all, delete-orphan")

# --- 新增展示頁模組 Tables ---

class CoachMedia(Base):
    __tablename__ = "coach_media"
    id = Column(Integer, primary_key=True, index=True)
    coach_id = Column(Integer, ForeignKey("coach_profiles.id"))
    type = Column(String)  # 'image' or 'video' or 'youtube_embed'
    url = Column(String)
    title = Column(String, nullable=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    coach = relationship("CoachProfile", back_populates="features_media")

class CoachLink(Base): # 教學連結
    __tablename__ = "coach_links"
    id = Column(Integer, primary_key=True, index=True)
    coach_id = Column(Integer, ForeignKey("coach_profiles.id"))
    text = Column(String)
    url = Column(String)
    icon = Column(String, default="link") 
    sort_order = Column(Integer, default=0)
    coach = relationship("CoachProfile", back_populates="features_links")

class CoachFaq(Base): # 常見問題
    __tablename__ = "coach_faq"
    id = Column(Integer, primary_key=True, index=True)
    coach_id = Column(Integer, ForeignKey("coach_profiles.id"))
    question = Column(String)
    answer = Column(String)
    sort_order = Column(Integer, default=0)
    coach = relationship("CoachProfile", back_populates="features_faq")

class CoachOffer(Base): # 課程方案
    __tablename__ = "coach_offers"
    id = Column(Integer, primary_key=True, index=True)
    coach_id = Column(Integer, ForeignKey("coach_profiles.id"))
    title = Column(String) 
    price_text = Column(String) 
    duration = Column(String) 
    description = Column(String)
    tags = Column(String) # JSON list
    sort_order = Column(Integer, default=0)
    coach = relationship("CoachProfile", back_populates="features_offers")

class CoachTestimonial(Base): # 學員見證
    __tablename__ = "coach_testimonials"
    id = Column(Integer, primary_key=True, index=True)
    coach_id = Column(Integer, ForeignKey("coach_profiles.id"))
    student_name = Column(String)
    content = Column(String)
    image_url = Column(String, nullable=True)
    is_pinned = Column(Boolean, default=False)
    coach = relationship("CoachProfile", back_populates="features_testimonials")

class CoachDailyMetric(Base): # 漏斗數據
    __tablename__ = "coach_daily_metrics"
    id = Column(Integer, primary_key=True, index=True)
    coach_id = Column(Integer, ForeignKey("coach_profiles.id"))
    date = Column(Date, index=True)
    impressions = Column(Integer, default=0)
    saves = Column(Integer, default=0)
    inquiries = Column(Integer, default=0)
    bookings = Column(Integer, default=0)
    
    coach = relationship("CoachProfile", back_populates="daily_metrics")
    
    __table_args__ = (
        UniqueConstraint('coach_id', 'date', name='uix_coach_date'),
    )

class CoachReviewLog(Base):
    __tablename__ = "coach_review_logs"
    id = Column(Integer, primary_key=True, index=True)
    coach_id = Column(Integer, ForeignKey("coach_profiles.id"))
    action = Column(String) # SUBMIT | APPROVE | REJECT
    actor_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    payload_json = Column(Text, default="{}") # Snapshots or reasons
    created_at = Column(DateTime, default=datetime.utcnow)

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String)
    content = Column(Text)
    link = Column(String) # For direct clicking
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    type = Column(String) # info, success, warning, danger

class InquiryThread(Base):
    __tablename__ = "inquiry_threads"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"))
    coach_profile_id = Column(Integer, ForeignKey("coach_profiles.id"))
    last_message = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

class InquiryMessage(Base):
    __tablename__ = "inquiry_messages"
    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("inquiry_threads.id"))
    sender_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

# --- Feature 1: Conversations (New) ---
class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"))
    coach_id = Column(Integer, ForeignKey("coach_profiles.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    last_message_at = Column(DateTime, default=datetime.utcnow)
    message_count = Column(Integer, default=0)
    status = Column(String, default="ACTIVE") # ACTIVE, CLOSED

class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    sender_role = Column(String) # 'student' | 'coach'
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    read_at = Column(DateTime, nullable=True)

# --- Feature 1: Bookings (New Core) ---
class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), index=True)
    coach_id = Column(Integer, ForeignKey("coach_profiles.id"), index=True)
    sport_type = Column(String)
    schedule_start_at = Column(DateTime, nullable=True)
    schedule_end_at = Column(DateTime, nullable=True)
    
    # REQUESTED | CONFIRMED | IN_PROGRESS | COMPLETED | CANCELED
    status = Column(String, default="REQUESTED", index=True) 
    
    created_at = Column(DateTime, default=datetime.utcnow)
    confirmed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    completed_by_student = Column(Boolean, default=False)
    completed_by_coach = Column(Boolean, default=False)
    completion_finalized_at = Column(DateTime, nullable=True)
    cancel_reason = Column(String, nullable=True)

# Update Review/Complaint/Lesson to be compatible or legacy
class Lesson(Base): 
    # Legacy: Kept to avoid breaking existing code immediately, 
    # but new flow will use Booking
    __tablename__ = "lessons"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"))
    coach_id = Column(Integer, ForeignKey("coach_profiles.id"))
    status = Column(String, default="BOOKED")
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    topic = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class Review(Base):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True, index=True)
    lesson_id = Column(Integer, ForeignKey("lessons.id"), unique=True, nullable=True) # Legacy
    booking_id = Column(Integer, ForeignKey("bookings.id"), unique=True, nullable=True) # New
    
    coach_id = Column(Integer, ForeignKey("coach_profiles.id"))
    student_id = Column(Integer, ForeignKey("users.id"))
    
    rating = Column(Float)
    comment = Column(Text)
    is_anonymous = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Complaint(Base):
    __tablename__ = "complaints"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"))
    coach_id = Column(Integer, ForeignKey("coach_profiles.id"))
    
    lesson_id = Column(Integer, ForeignKey("lessons.id"), nullable=True) # Legacy
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True) # New
    
    thread_id = Column(Integer, ForeignKey("inquiry_threads.id"), nullable=True) # Legacy
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True) # New
    
    category = Column(String)
    description = Column(Text)
    attachment_url = Column(String, nullable=True)
    is_anonymous = Column(Boolean, default=False)
    status = Column(String, default="PENDING")
    created_at = Column(DateTime, default=datetime.utcnow)

class AdminCase(Base):
    __tablename__ = "admin_cases"
    id = Column(Integer, primary_key=True, index=True)
    
    # COACH_ONBOARD_REVIEW / COACH_UPDATE_REVIEW / LOW_RATING / COMPLAINT
    case_type = Column(String, index=True)
    
    # OPEN / IN_REVIEW / NEED_INFO / RESOLVED / REJECTED / CLOSED
    status = Column(String, default="OPEN", index=True)
    
    coach_id = Column(Integer, ForeignKey("coach_profiles.id"), index=True)
    
    # REVIEW / COMPLAINT / SYSTEM / UPDATE_SUBMIT
    trigger_source_type = Column(String, nullable=True)
    trigger_source_id = Column(Integer, nullable=True) # ref_id
    
    priority = Column(String, default="MED") # LOW / MED / HIGH
    
    admin_assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    admin_note = Column(Text, nullable=True)
    
    # APPROVE_REINSTATE / KEEP_SUSPENDED / BAN / REQUEST_INFO / REJECT_CASE
    action = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    
    # Legacy field mapping if needed
    trigger_type = Column(String, nullable=True) # Mapping to case_type
    ref_id = Column(Integer, nullable=True) # Mapping to trigger_source_id
    result_note = Column(Text, nullable=True) # Mapping to admin_note
    handler_id = Column(Integer, nullable=True) # Mapping to admin_assignee_id

class Favorite(Base):
    __tablename__ = "favorites"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"),  index=True)
    coach_id = Column(Integer, ForeignKey("coach_profiles.id"), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('student_id', 'coach_id', name='_student_coach_fav_uc'),)

# --- Feature 3: Admin Support Chat ---
class AdminConversation(Base):
    __tablename__ = "admin_conversations"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id")) # Student or Coach
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=True) # Assigned admin
    subject = Column(String)
    is_closed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    messages = relationship("AdminMessage", back_populates="conversation")

class AdminMessage(Base):
    __tablename__ = "admin_messages"
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("admin_conversations.id"))
    sender_id = Column(Integer, ForeignKey("users.id")) 
    sender_role = Column(String) # 'admin' or 'user'
    content = Column(Text)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    conversation = relationship("AdminConversation", back_populates="messages")

# --- Feature 2: Rate Limit ---
class RateLimit(Base):
    __tablename__ = "rate_limits"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, index=True) # "user:1:POST:/api..."
    window_start_at = Column(DateTime)
    count = Column(Integer, default=0)

# --- Feature 4: Analytics ---
class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=True)
    session_id = Column(String, nullable=True)
    event_type = Column(String, index=True) # PAGE_HOME, VIEW_COACH...
    coach_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

# --- Feature 5: Coach Subscriptions & Events (New) ---
class CoachSubscription(Base):
    __tablename__ = "coach_subscriptions"
    id = Column(Integer, primary_key=True, index=True)
    coach_id = Column(Integer, ForeignKey("coach_profiles.id"))
    plan_id = Column(String) # 'free', 'pro', 'elite'
    start_at = Column(DateTime, default=datetime.utcnow)
    end_at = Column(DateTime)
    is_active = Column(Integer, default=1) # 0/1 (Boolean logic)
    source = Column(String, default="demo") # 'manual' | 'demo'
    created_at = Column(DateTime, default=datetime.utcnow)

class CoachPlan(Base):
    __tablename__ = "coach_plans"
    plan_id = Column(String, primary_key=True)
    name_zh = Column(String) # 教練方案名稱
    features_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String, index=True) 
    # impression_coach, favorite_add, inquiry_create, booking_create, plan_upgrade
    user_id = Column(Integer, nullable=True)
    coach_id = Column(Integer, nullable=True)
    meta_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
