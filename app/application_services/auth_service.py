from __future__ import annotations

import base64
from datetime import datetime, timedelta
import hashlib
import hmac
import os
import secrets
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.services.email_service import EmailDeliveryError, ResendEmailSender
from app.serving.models import User


class EmailNotVerifiedError(ValueError):
    pass


class AuthService:
    def __init__(
        self,
        db: Session,
        emailSender: ResendEmailSender | None = None,
        verificationSecret: str | None = None,
    ):
        self.db = db
        self.emailSender = emailSender or ResendEmailSender()
        self.verificationSecret = (
            verificationSecret
            if verificationSecret is not None
            else os.getenv("EMAIL_VERIFICATION_SECRET", "")
        )
        self.verificationTtlMinutes = int(os.getenv("EMAIL_VERIFICATION_TTL_MINUTES", "10"))
        self.resendCooldownSeconds = int(
            os.getenv("EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS", "60")
        )
        self.maxVerificationAttempts = int(
            os.getenv("EMAIL_VERIFICATION_MAX_ATTEMPTS", "5")
        )

    def register(
        self,
        username: str,
        email: str,
        password: str,
        birthDate: date | None = None,
        gender: str | None = None,
        termsVersion: str | None = None,
        privacyPolicyVersion: str | None = None,
    ) -> User:
        self._requireVerificationConfiguration()
        normalized_email = email.strip().lower()
        existing = (
            self.db.query(User)
            .filter((User.username == username) | (func.lower(User.email) == normalized_email))
            .first()
        )
        if existing:
            raise ValueError("El usuario o email ya existe.")

        now = datetime.utcnow()
        user = User(
            username=username,
            email=normalized_email,
            password_hash=self.hashPassword(password),
            birth_date=birthDate,
            gender=gender.strip().lower() if gender else None,
            role="user",
            terms_version=termsVersion,
            terms_accepted_at=now,
            privacy_policy_version=privacyPolicyVersion,
            privacy_policy_accepted_at=now,
        )
        user.register()
        self.db.add(user)
        code = self._issueVerificationCode(user, now)
        try:
            self.db.flush()
            self.emailSender.sendVerificationCode(user.email, code)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(user)
        return user

    def login(self, email: str, password: str) -> User:
        normalized_email = email.strip().lower()
        user = self.db.query(User).filter(func.lower(User.email) == normalized_email).first()
        if not user or not self.verifyPassword(password, user.password_hash):
            raise ValueError("Credenciales invalidas.")
        if user.email_verified_at is None:
            raise EmailNotVerifiedError("Debes confirmar tu correo antes de iniciar sesión.")
        return user

    def verifyEmail(self, email: str, code: str) -> User:
        normalized_email = email.strip().lower()
        user = self.db.query(User).filter(func.lower(User.email) == normalized_email).first()
        if not user:
            raise ValueError("El código de confirmación es inválido o venció.")
        if user.email_verified_at is not None:
            return user

        now = datetime.utcnow()
        if (
            not user.email_verification_code_hash
            or not user.email_verification_expires_at
            or user.email_verification_expires_at < now
        ):
            raise ValueError("El código de confirmación venció. Solicita uno nuevo.")
        if user.email_verification_attempts >= self.maxVerificationAttempts:
            raise ValueError("Se agotaron los intentos. Solicita un código nuevo.")

        user.email_verification_attempts += 1
        if not hmac.compare_digest(
            user.email_verification_code_hash,
            self._hashVerificationCode(code),
        ):
            self.db.commit()
            raise ValueError("El código de confirmación es inválido o venció.")

        user.email_verified_at = now
        user.email_verification_code_hash = None
        user.email_verification_expires_at = None
        user.email_verification_attempts = 0
        self.db.commit()
        self.db.refresh(user)
        return user

    def resendVerification(self, email: str) -> None:
        self._requireVerificationConfiguration()
        normalized_email = email.strip().lower()
        user = self.db.query(User).filter(func.lower(User.email) == normalized_email).first()
        if not user:
            raise ValueError("No existe una cuenta pendiente para ese correo.")
        if user.email_verified_at is not None:
            raise ValueError("Ese correo ya fue confirmado.")

        now = datetime.utcnow()
        if user.email_verification_sent_at:
            elapsed = (now - user.email_verification_sent_at).total_seconds()
            if elapsed < self.resendCooldownSeconds:
                remaining = max(1, int(self.resendCooldownSeconds - elapsed))
                raise ValueError(f"Espera {remaining} segundos para solicitar otro código.")

        code = self._issueVerificationCode(user, now)
        try:
            self.db.flush()
            self.emailSender.sendVerificationCode(user.email, code)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _requireVerificationConfiguration(self) -> None:
        if not self.verificationSecret:
            raise EmailDeliveryError("El servicio de correo no está configurado.")

    def _issueVerificationCode(self, user: User, now: datetime) -> str:
        code = f"{secrets.randbelow(900000) + 100000:06d}"
        user.email_verification_code_hash = self._hashVerificationCode(code)
        user.email_verification_expires_at = now + timedelta(
            minutes=self.verificationTtlMinutes
        )
        user.email_verification_sent_at = now
        user.email_verification_attempts = 0
        return code

    def _hashVerificationCode(self, code: str) -> str:
        return hmac.new(
            self.verificationSecret.encode("utf-8"),
            code.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def hashPassword(self, password: str) -> str:
        salt = os.urandom(16)
        derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120000)
        return f"{base64.b64encode(salt).decode()}:{base64.b64encode(derived).decode()}"

    def verifyPassword(self, password: str, passwordHash: str) -> bool:
        try:
            salt_b64, derived_b64 = passwordHash.split(":")
        except ValueError:
            return False
        salt = base64.b64decode(salt_b64.encode())
        expected = base64.b64decode(derived_b64.encode())
        current = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120000)
        return hmac.compare_digest(expected, current)
