from typing import List, Dict, Optional, Any, Tuple
from sqlalchemy.orm import Session
from datetime import datetime
from . import models

# --- Coach State Machine ---
# --- Coach State Machine ---
COACH_REVIEW_STATUS = ["DRAFT", "PENDING_REVIEW", "APPROVED", "REJECTED", "SUSPENDED", "BANNED"]
COACH_VISIBILITY = ["HIDDEN", "VISIBLE"]
COACH_ACCOUNT = ["ACTIVE", "SUSPENDED"]

COACH_TRANSITIONS = {
    "review": {
        ("DRAFT", "PENDING_REVIEW"): ["coach"],
        ("PENDING_REVIEW", "APPROVED"): ["admin"],
        ("PENDING_REVIEW", "REJECTED"): ["admin"],
        ("APPROVED", "PENDING_REVIEW"): ["coach"],
        ("REJECTED", "PENDING_REVIEW"): ["coach"],
        # Governance Transitions
        ("APPROVED", "SUSPENDED"): ["admin"],
        ("APPROVED", "BANNED"): ["admin"],
        ("SUSPENDED", "APPROVED"): ["admin"],
        ("SUSPENDED", "BANNED"): ["admin"],
        ("BANNED", "APPROVED"): ["admin"],
    }
}

# --- Admin Case Machine ---
CASE_TRANSITIONS = {
    ("OPEN", "IN_REVIEW"): ["admin"],
    ("IN_REVIEW", "NEED_INFO"): ["admin"],
    ("NEED_INFO", "IN_REVIEW"): ["admin", "coach"],
    ("IN_REVIEW", "RESOLVED"): ["admin"],
    ("IN_REVIEW", "REJECTED"): ["admin"],
    ("RESOLVED", "CLOSED"): ["admin"],
    ("REJECTED", "CLOSED"): ["admin"]
}

class StatusService:
    # --- Coach Logic ---
    @staticmethod
    def can_transition_coach(coach: models.CoachProfile, next_review: str, role: str) -> bool:
        current = coach.review_status or "DRAFT"
        allowed_roles = COACH_TRANSITIONS["review"].get((current, next_review), [])
        return role in allowed_roles

    @staticmethod
    def apply_coach_transition(db: Session, coach: models.CoachProfile, next_review: str, actor_role: str):
        if not StatusService.can_transition_coach(coach, next_review, actor_role):
            return False, f"Invalid transition from {coach.review_status} to {next_review}"

        coach.review_status = next_review
        
        if next_review == "APPROVED":
            coach.visibility_status = "VISIBLE"
            coach.approved_at = datetime.utcnow()
        else:
            coach.visibility_status = "HIDDEN"
            
        if coach.account_status == "SUSPENDED":
            coach.visibility_status = "HIDDEN"
            
        db.commit()
        
        # If transition is to PENDING_REVIEW, auto create Case
        if next_review == "PENDING_REVIEW":
            case_type = "COACH_ONBOARD_REVIEW" if not coach.approved_at else "COACH_UPDATE_REVIEW"
            StatusService.create_admin_case(db, coach.id, case_type, "SYSTEM", None)
            
        return True, "Done"

    @staticmethod
    @staticmethod
    def suspend_coach(db: Session, coach: models.CoachProfile, reason: str, case_type: str, source_id: int):
        # Do NOT auto-suspend immediately. Just create High Priority case.
        # coach.account_status = "SUSPENDED" 
        # coach.visibility_status = "HIDDEN"
        # coach.suspension_reason = reason
        
        # Create Case
        StatusService.create_admin_case(db, coach.id, case_type, case_type, source_id, priority="HIGH")
        
        # Notify Coach
        from .services.notification_service import NotificationService
        NotificationService.create_notification(
            db, 
            coach.user_id, 
            "收到新的投訴案件", 
            "平台收到關於您的投訴，目前已立案調查中。請留意管理員後續通知。", 
            "/account/coach",
            "warning"
        )
        db.commit()

    # --- Case Logic ---
    @staticmethod
    def create_admin_case(db: Session, coach_id: int, case_type: str, source_type: str, source_id: Optional[int], priority: str = "MED"):
        # Check if active case of same type exists
        existing = db.query(models.AdminCase).filter(
            models.AdminCase.coach_id == coach_id,
            models.AdminCase.case_type == case_type,
            models.AdminCase.status.in_(["OPEN", "IN_REVIEW", "NEED_INFO"])
        ).first()
        if existing: return existing
        
        case = models.AdminCase(
            coach_id=coach_id,
            case_type=case_type,
            trigger_source_type=source_type,
            trigger_source_id=source_id,
            priority=priority,
            status="OPEN"
        )
        db.add(case)
        db.commit()
        return case

    @staticmethod
    def apply_case_transition(db: Session, case: models.AdminCase, next_status: str, role: str) -> Tuple[bool, str]:
        if (case.status, next_status) not in CASE_TRANSITIONS:
            return False, f"No transition from {case.status} to {next_status}"
        
        allowed_roles = CASE_TRANSITIONS[(case.status, next_status)]
        if role not in allowed_roles:
            return False, "Permission denied"
            
        case.status = next_status
        db.commit()
        return True, "Success"

    @staticmethod
    def resolve_case(db: Session, case: models.AdminCase, action: str, admin_note: str, admin_id: int):
        from .services.notification_service import NotificationService
        
        case.action = action
        case.admin_note = admin_note
        case.admin_assignee_id = admin_id
        
        coach = db.query(models.CoachProfile).filter(models.CoachProfile.id == case.coach_id).first()
        complaint = None
        if case.trigger_source_type == "COMPLAINT":
            complaint = db.query(models.Complaint).filter(models.Complaint.id == case.trigger_source_id).first()

        if action == "CONFIRM_VIOLATION": # 判定違規 / 執行停權
            case.status = "RESOLVED"
            case.resolved_at = datetime.utcnow()
            
            if coach:
                coach.account_status = "SUSPENDED"
                coach.visibility_status = "HIDDEN"
                coach.suspension_reason = f"Admin Case #{case.id}: {admin_note}"
                
                # Create Admin Support Chat automatically
                support_chat = db.query(models.AdminConversation).filter(
                    models.AdminConversation.user_id == coach.user_id
                ).first()
                
                subject_text = f"帳號停權申訴 (Case #{case.id})"
                
                if not support_chat:
                    support_chat = models.AdminConversation(
                        user_id=coach.user_id,
                        subject=subject_text
                    )
                    db.add(support_chat)
                    db.flush()
                else:
                    support_chat.subject = subject_text
                    support_chat.updated_at = datetime.utcnow()

                # Notify Coach
                NotificationService.create_notification(
                    db, coach.user_id, "帳號停權通知", 
                    f"您的帳號已被管理員停權。原因：{admin_note}。如有疑問已為您開設申訴對話窗口，請至訊息中心查看。", 
                    f"/messages/support/{support_chat.id}", "danger"
                )
                
                # Initial System Message
                sys_msg = models.AdminMessage(
                    conversation_id=support_chat.id,
                    sender_id=admin_id, # Sent by the admin handling the case
                    sender_role="admin",
                    content=f"系統通知：您的帳號因違反平台規定而被停權。案件 #{case.id}。\n判決原因：{admin_note}\n您可以直接回覆此訊息進行申訴。",
                    is_read=True
                )
                db.add(sys_msg)
                
            # Notify Student
            if complaint:
                # Create System Chat for Student
                student_chat = models.AdminConversation(
                    user_id=complaint.student_id,
                    subject=f"投訴處理通知 (Case #{case.id})"
                )
                db.add(student_chat)
                db.flush()
                
                # System Message
                sys_msg_s = models.AdminMessage(
                    conversation_id=student_chat.id,
                    sender_id=admin_id,
                    sender_role="admin",
                    content=f"系統通知：您提交的投訴 (Case #{case.id}) 經審核判定違規成立，已對教練進行處分。\n感謝您對維護平台環境的貢獻。",
                    is_read=False
                )
                db.add(sys_msg_s)
                
                NotificationService.create_notification(
                    db, complaint.student_id, "投訴案件處理結果",
                    f"您提交的投訴 (案件 #{case.id}) 已有處理結果，請點擊查看詳情。",
                    f"/messages/support/{student_chat.id}", "success"
                )

        elif action == "DISMISS": # 無違規 / 結案
            case.status = "RESOLVED"
            case.resolved_at = datetime.utcnow()
            
            # Notify Student only
            if complaint:
                # Create System Chat for Student
                student_chat = models.AdminConversation(
                    user_id=complaint.student_id,
                    subject=f"投訴處理通知 (Case #{case.id})"
                )
                db.add(student_chat)
                db.flush()
                
                # System Message
                sys_msg_s = models.AdminMessage(
                    conversation_id=student_chat.id,
                    sender_id=admin_id,
                    sender_role="admin",
                    content=f"系統通知：您提交的投訴 (Case #{case.id}) 經審核後判定無明確違規，案件已結案。\n若有新事證請再次聯繫我們。",
                    is_read=False
                )
                db.add(sys_msg_s)

                NotificationService.create_notification(
                    db, complaint.student_id, "投訴案件處理結果",
                    f"您提交的投訴 (案件 #{case.id}) 經審核判定案件不成立。請查看詳情。",
                    f"/messages/support/{student_chat.id}", "info"
                )

        elif action == "REJECT_RETURN": # 證據不足 / 駁回 (Status -> NEED_INFO / Processing)
            case.status = "NEED_INFO" # Maps to "Processing" with note
            # Notify Student
            if complaint:
                # Create System Chat for Student
                student_chat = db.query(models.AdminConversation).filter(
                    models.AdminConversation.user_id == complaint.student_id
                ).first()
                
                subject_text = f"投訴補充資料通知 (Case #{case.id})"
                
                if not student_chat:
                    student_chat = models.AdminConversation(
                        user_id=complaint.student_id,
                        subject=subject_text
                    )
                    db.add(student_chat)
                    db.flush()
                else:
                    student_chat.subject = subject_text
                    student_chat.updated_at = datetime.utcnow()
                
                # System Message
                sys_msg_s = models.AdminMessage(
                    conversation_id=student_chat.id,
                    sender_id=admin_id,
                    sender_role="admin",
                    content=f"系統通知：您提交的投訴 (Case #{case.id}) 因證據不足暫被退回。\n原因：{admin_note}\n請直接在此對話中上傳補充證明檔案或說明。",
                    is_read=False
                )
                db.add(sys_msg_s)
                
                NotificationService.create_notification(
                    db, complaint.student_id, "投訴案件需補充資訊",
                    f"您提交的投訴 (案件 #{case.id}) 需要補充證明。請點擊前往回覆。",
                    f"/messages/support/{student_chat.id}", "warning"
                )

        elif action == "BAN":
            case.status = "RESOLVED"
            case.resolved_at = datetime.utcnow()
            if coach:
                coach.account_status = "SUSPENDED"
                coach.visibility_status = "HIDDEN"
                coach.is_banned = True

        # Legacy / Reset
        elif action == "APPROVE_REINSTATE": 
             case.status = "RESOLVED"
             case.resolved_at = datetime.utcnow()
             if coach:
                coach.account_status = "ACTIVE"
                coach.visibility_status = "VISIBLE"
            
        db.commit()

    # --- Booking Logic ---
    @staticmethod
    def apply_booking_transition(db: Session, booking: models.Booking, next_status: str, role: str):
        current = booking.status
        if current == "REQUESTED" and next_status == "CONFIRMED" and role == "coach":
            booking.status = "CONFIRMED"
            booking.confirmed_at = datetime.utcnow()
        elif current == "REQUESTED" and next_status == "CANCELED" and role in ["coach", "student"]:
            booking.status = "CANCELED"
        elif current == "CONFIRMED" and next_status == "IN_PROGRESS" and role == "coach":
            booking.status = "IN_PROGRESS"
        elif next_status == "COMPLETED":
            if role == "student": booking.completed_by_student = True
            if role == "coach": booking.completed_by_coach = True
            if booking.completed_by_student and booking.completed_by_coach:
                booking.status = "COMPLETED"
                booking.completion_finalized_at = datetime.utcnow()
        db.commit()
        return True
