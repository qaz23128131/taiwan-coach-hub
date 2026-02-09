from sqlalchemy.orm import Session
from .. import models
from datetime import datetime
import json

class NotificationService:
    @staticmethod
    def create_notification(db: Session, user_id: int, title: str, content: str, link: str = None, type: str = "info"):
        notif = models.Notification(
            user_id=user_id,
            title=title,
            content=content,
            link=link,
            type=type
        )
        db.add(notif)
        db.commit()
