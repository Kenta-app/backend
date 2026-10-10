from __future__ import annotations

import logging
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services.email_service import EmailDeliveryError, ResendEmailSender
from app.serving.models import DrawConfirmation, User

logger = logging.getLogger(__name__)

DRAW_ID = "sorteo-kenta-2026-10-10"
DRAW_DATE = date(2026, 10, 10)
DRAW_TIMEZONE = ZoneInfo("America/Lima")
DEFAULT_WINNER_EMAIL = "u202216148@up.edu.pe"


def configured_winner_email() -> str:
    """Allows a non-production winner override for controlled local testing."""
    return os.getenv("KENTA_DRAW_WINNER_EMAIL", DEFAULT_WINNER_EMAIL).strip().lower()


class DrawConfirmationError(ValueError):
    pass


class DrawAlreadyConfirmedError(DrawConfirmationError):
    pass


class DrawService:
    def __init__(
        self,
        db: Session,
        emailSender: ResendEmailSender | None = None,
        nowProvider=None,
    ):
        self.db = db
        self.emailSender = emailSender or ResendEmailSender()
        self.nowProvider = nowProvider or (lambda: datetime.now(DRAW_TIMEZONE))

    def confirmRead(self, user: User, drawId: str) -> DrawConfirmation:
        self._validateDraw(user, drawId)
        existing = (
            self.db.query(DrawConfirmation)
            .filter(
                DrawConfirmation.user_id == user.user_id,
                DrawConfirmation.draw_id == drawId,
            )
            .first()
        )
        if existing:
            raise DrawAlreadyConfirmedError("Los datos de este sorteo ya fueron confirmados.")

        confirmation = DrawConfirmation(
            draw_id=drawId,
            user_id=user.user_id,
            confirmed_at=datetime.utcnow(),
        )
        self.db.add(confirmation)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise DrawAlreadyConfirmedError(
                "Los datos de este sorteo ya fueron confirmados."
            ) from exc
        self.db.refresh(confirmation)
        self._sendConfirmationEmails(user, confirmation)
        return confirmation

    def _validateDraw(self, user: User, drawId: str) -> None:
        if drawId != DRAW_ID:
            raise DrawConfirmationError("El sorteo indicado no es válido.")
        now = self.nowProvider()
        if now.tzinfo is None:
            now = now.replace(tzinfo=DRAW_TIMEZONE)
        if now.astimezone(DRAW_TIMEZONE).date() != DRAW_DATE:
            raise DrawConfirmationError("El sorteo no está vigente.")
        if user.email.strip().lower() != configured_winner_email():
            raise DrawConfirmationError("No estás autorizado para confirmar este sorteo.")

    def _sendConfirmationEmails(self, user: User, confirmation: DrawConfirmation) -> None:
        try:
            self.emailSender.sendDrawConfirmation(user.email, user.username, confirmation.draw_id)
            team_email = os.getenv("KENTA_DRAW_NOTIFICATION_EMAIL", "").strip()
            if team_email:
                self.emailSender.sendDrawTeamNotification(
                    team_email, user.email, confirmation.draw_id
                )
        except EmailDeliveryError as exc:
            # The confirmation is already durable; a mail outage must not invite a retry.
            logger.exception(
                "Unable to send draw confirmation email for user_id=%s: %s",
                user.user_id,
                exc,
            )
