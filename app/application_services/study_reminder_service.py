from __future__ import annotations

from datetime import datetime, timedelta
import logging
import os

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.services.email_service import EmailDeliveryError, ResendEmailSender
from app.serving.models import User

logger = logging.getLogger(__name__)


def configured_study_reminder_delay_hours() -> int:
    value = int(os.getenv("STUDY_REMINDER_DELAY_HOURS", "48"))
    if value < 24 or value > 168:
        raise ValueError("STUDY_REMINDER_DELAY_HOURS must be between 24 and 168.")
    return value


def configured_study_reminder_batch_size() -> int:
    value = int(os.getenv("STUDY_REMINDER_BATCH_SIZE", "20"))
    if value < 1 or value > 100:
        raise ValueError("STUDY_REMINDER_BATCH_SIZE must be between 1 and 100.")
    return value


class StudyReminderService:
    def __init__(
        self,
        db: Session,
        emailSender: ResendEmailSender | None = None,
        nowProvider=None,
    ):
        self.db = db
        self.emailSender = emailSender or ResendEmailSender()
        self.nowProvider = nowProvider or datetime.utcnow
        self.delayHours = configured_study_reminder_delay_hours()
        self.retryHours = int(os.getenv("STUDY_REMINDER_RETRY_HOURS", "6"))
        self.maxAttempts = int(os.getenv("STUDY_REMINDER_MAX_ATTEMPTS", "3"))
        if self.retryHours < 1 or self.retryHours > 48:
            raise ValueError("STUDY_REMINDER_RETRY_HOURS must be between 1 and 48.")
        if self.maxAttempts < 1 or self.maxAttempts > 5:
            raise ValueError("STUDY_REMINDER_MAX_ATTEMPTS must be between 1 and 5.")

    def sendDueReminders(self, limit: int | None = None) -> dict[str, int]:
        now = self.nowProvider()
        batch_size = limit if limit is not None else configured_study_reminder_batch_size()
        if batch_size < 1 or batch_size > 100:
            raise ValueError("Reminder limit must be between 1 and 100.")

        due_before = now - timedelta(hours=self.delayHours)
        retry_before = now - timedelta(hours=self.retryHours)
        users = (
            self.db.query(User)
            .filter(
                User.role == "user",
                User.email_verified_at.isnot(None),
                User.study_reminder_opted_in_at.isnot(None),
                User.study_reminder_sent_at.is_(None),
                User.created_at <= due_before,
                User.study_reminder_attempts < self.maxAttempts,
                or_(
                    User.study_reminder_last_attempt_at.is_(None),
                    User.study_reminder_last_attempt_at <= retry_before,
                ),
            )
            .order_by(User.created_at.asc(), User.user_id.asc())
            .limit(batch_size)
            .all()
        )

        sent = 0
        failed = 0
        for user in users:
            user.study_reminder_attempts = int(user.study_reminder_attempts or 0) + 1
            user.study_reminder_last_attempt_at = now
            user.study_reminder_last_error = None
            self.db.commit()
            try:
                self.emailSender.sendStudyReminder(user.email, user.username)
            except EmailDeliveryError as exc:
                user.study_reminder_last_error = str(exc)[:1000]
                self.db.commit()
                failed += 1
                logger.warning(
                    "Study reminder failed user_id=%s attempt=%s: %s",
                    user.user_id,
                    user.study_reminder_attempts,
                    exc,
                )
                continue

            user.study_reminder_sent_at = self.nowProvider()
            self.db.commit()
            sent += 1

        return {"eligible": len(users), "sent": sent, "failed": failed}
