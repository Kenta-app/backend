from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application_services.study_reminder_service import StudyReminderService
from app.db.database import apply_sqlite_schema_translation
from app.services.email_service import EmailDeliveryError
from app.serving.models import User


class FakeReminderSender:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.messages = []

    def sendStudyReminder(self, email: str, username: str) -> None:
        if self.should_fail:
            raise EmailDeliveryError("temporary failure")
        self.messages.append({"email": email, "username": username})


def build_user(email: str, now: datetime, **overrides) -> User:
    values = {
        "username": email.split("@", 1)[0],
        "email": email,
        "password_hash": "unused",
        "role": "user",
        "created_at": now - timedelta(hours=49),
        "email_verified_at": now - timedelta(hours=48),
        "study_reminder_opted_in_at": now - timedelta(hours=49),
    }
    values.update(overrides)
    return User(**values)


def test_only_due_consented_participant_receives_one_reminder(monkeypatch):
    monkeypatch.setenv("STUDY_REMINDER_DELAY_HOURS", "48")
    now = datetime(2026, 10, 5, 18, 0, 0)
    engine = apply_sqlite_schema_translation(create_engine("sqlite:///:memory:"))
    User.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    try:
        due = build_user("due@example.com", now)
        db.add_all(
            [
                due,
                build_user("recent@example.com", now, created_at=now - timedelta(hours=12)),
                build_user("no-consent@example.com", now, study_reminder_opted_in_at=None),
                build_user("unverified@example.com", now, email_verified_at=None),
                build_user("admin@example.com", now, role="admin"),
            ]
        )
        db.commit()
        sender = FakeReminderSender()
        service = StudyReminderService(db, sender, nowProvider=lambda: now)

        assert service.sendDueReminders() == {"eligible": 1, "sent": 1, "failed": 0}
        assert sender.messages == [{"email": "due@example.com", "username": "due"}]
        assert due.study_reminder_sent_at == now
        assert due.study_reminder_attempts == 1
        assert service.sendDueReminders() == {"eligible": 0, "sent": 0, "failed": 0}
    finally:
        db.close()
        engine.dispose()


def test_failed_reminder_is_recorded_and_not_retried_immediately(monkeypatch):
    monkeypatch.setenv("STUDY_REMINDER_DELAY_HOURS", "48")
    monkeypatch.setenv("STUDY_REMINDER_RETRY_HOURS", "6")
    now = datetime(2026, 10, 5, 18, 0, 0)
    engine = apply_sqlite_schema_translation(create_engine("sqlite:///:memory:"))
    User.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    try:
        user = build_user("failure@example.com", now)
        db.add(user)
        db.commit()
        service = StudyReminderService(
            db,
            FakeReminderSender(should_fail=True),
            nowProvider=lambda: now,
        )

        assert service.sendDueReminders() == {"eligible": 1, "sent": 0, "failed": 1}
        assert user.study_reminder_sent_at is None
        assert user.study_reminder_attempts == 1
        assert user.study_reminder_last_error == "temporary failure"
        assert service.sendDueReminders() == {"eligible": 0, "sent": 0, "failed": 0}
    finally:
        db.close()
        engine.dispose()
