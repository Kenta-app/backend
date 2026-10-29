from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta
import hashlib
import hmac
import logging
import os
import secrets
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.services.email_service import EmailDeliveryError, ResendEmailSender
from app.serving.models import PasswordResetRequest, User


logger = logging.getLogger(__name__)


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
        self.passwordResetSecret = os.getenv("PASSWORD_RESET_SECRET", "")
        self.passwordResetTtlMinutes = int(os.getenv("PASSWORD_RESET_TTL_MINUTES", "20"))
        self.passwordResetWindowMinutes = int(
            os.getenv("PASSWORD_RESET_WINDOW_MINUTES", "15")
        )
        self.passwordResetMaxPerEmail = int(
            os.getenv("PASSWORD_RESET_MAX_REQUESTS_PER_EMAIL", "3")
        )
        self.passwordResetMaxPerIp = int(
            os.getenv("PASSWORD_RESET_MAX_REQUESTS_PER_IP", "10")
        )
        self.passwordResetRetentionDays = int(
            os.getenv("PASSWORD_RESET_RETENTION_DAYS", "7")
        )
        self.passwordHashIterations = int(
            os.getenv("PASSWORD_HASH_ITERATIONS", "600000")
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
        studyReminderOptIn: bool = False,
    ) -> User:
        self._requireVerificationConfiguration()
        normalized_email = email.strip().lower()
        existing = (
            self.db.query(User)
            .filter(
                (func.lower(User.username) == username.lower())
                | (func.lower(User.email) == normalized_email)
            )
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
            study_reminder_opted_in_at=now if studyReminderOptIn else None,
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
        if self._passwordHashNeedsUpgrade(user.password_hash):
            user.password_hash = self.hashPassword(password)
            self.db.commit()
            self.db.refresh(user)
        return user

    def changePassword(self, user: User, currentPassword: str, newPassword: str) -> User:
        if not self.verifyPassword(currentPassword, user.password_hash):
            raise ValueError("La contraseña actual es incorrecta.")
        if self.verifyPassword(newPassword, user.password_hash):
            raise ValueError("La nueva contraseña debe ser distinta de la actual.")
        user.password_hash = self.hashPassword(newPassword)
        self.db.commit()
        self.db.refresh(user)
        return user

    def requestPasswordReset(
        self, email: str, clientIp: str
    ) -> tuple[str, str] | None:
        """Record a reset request and return delivery data only for a real account.

        The controller always returns the same public response. Email delivery is
        scheduled after the response to avoid an account-existence timing signal.
        """
        self._requirePasswordResetConfiguration()
        normalized_email = email.strip().lower()
        normalized_ip = (clientIp or "unknown").strip().lower()
        email_fingerprint = self._passwordResetFingerprint(
            "email", normalized_email
        )
        ip_fingerprint = self._passwordResetFingerprint("ip", normalized_ip)
        now = datetime.utcnow()
        window_start = now - timedelta(minutes=self.passwordResetWindowMinutes)
        retention_start = now - timedelta(days=self.passwordResetRetentionDays)
        (
            self.db.query(PasswordResetRequest)
            .filter(PasswordResetRequest.requested_at < retention_start)
            .delete(synchronize_session=False)
        )

        email_count = (
            self.db.query(PasswordResetRequest)
            .filter(
                PasswordResetRequest.email_fingerprint == email_fingerprint,
                PasswordResetRequest.requested_at >= window_start,
            )
            .count()
        )
        ip_count = (
            self.db.query(PasswordResetRequest)
            .filter(
                PasswordResetRequest.ip_fingerprint == ip_fingerprint,
                PasswordResetRequest.requested_at >= window_start,
            )
            .count()
        )
        if (
            email_count >= self.passwordResetMaxPerEmail
            or ip_count >= self.passwordResetMaxPerIp
        ):
            return None

        user = (
            self.db.query(User)
            .filter(func.lower(User.email) == normalized_email)
            .first()
        )
        request_row = PasswordResetRequest(
            user_id=user.user_id if user else None,
            email_fingerprint=email_fingerprint,
            ip_fingerprint=ip_fingerprint,
            requested_at=now,
        )

        delivery: tuple[str, str] | None = None
        if user:
            token = secrets.token_urlsafe(32)
            request_row.token_hash = self._hashPasswordResetToken(token)
            request_row.expires_at = now + timedelta(
                minutes=self.passwordResetTtlMinutes
            )
            (
                self.db.query(PasswordResetRequest)
                .filter(
                    PasswordResetRequest.user_id == user.user_id,
                    PasswordResetRequest.used_at.is_(None),
                )
                .update({PasswordResetRequest.used_at: now}, synchronize_session=False)
            )
            delivery = (user.email, token)

        self.db.add(request_row)
        self.db.commit()
        return delivery

    def sendPasswordResetEmail(self, email: str, token: str) -> None:
        """Deliver a reset link without exposing provider failures to the client."""
        try:
            self.emailSender.sendPasswordResetLink(email, token)
        except Exception:
            logger.exception("Password-reset email delivery failed")

    def sendPasswordChangedNotice(self, email: str) -> None:
        try:
            self.emailSender.sendPasswordChangedNotice(email)
        except Exception:
            logger.exception("Password-change notification delivery failed")

    def resetPassword(self, token: str, newPassword: str) -> User:
        self._requirePasswordResetConfiguration()
        now = datetime.utcnow()
        token_hash = self._hashPasswordResetToken(token)
        reset_request = (
            self.db.query(PasswordResetRequest)
            .filter(PasswordResetRequest.token_hash == token_hash)
            .first()
        )
        if (
            not reset_request
            or reset_request.user_id is None
            or reset_request.used_at is not None
            or reset_request.expires_at is None
            or reset_request.expires_at < now
        ):
            raise ValueError("El enlace de recuperación es inválido o venció.")

        user = self.db.query(User).filter(User.user_id == reset_request.user_id).first()
        if not user:
            raise ValueError("El enlace de recuperación es inválido o venció.")
        if self.verifyPassword(newPassword, user.password_hash):
            raise ValueError("La nueva contraseña debe ser distinta de la actual.")

        user.password_hash = self.hashPassword(newPassword)
        (
            self.db.query(PasswordResetRequest)
            .filter(
                PasswordResetRequest.user_id == user.user_id,
                PasswordResetRequest.used_at.is_(None),
            )
            .update({PasswordResetRequest.used_at: now}, synchronize_session=False)
        )
        self.db.commit()
        self.db.refresh(user)
        return user

    def updateProfile(
        self,
        user: User,
        username: str,
        birthDate: date | None,
        gender: str | None,
    ) -> User:
        normalized_username = " ".join(username.split())
        existing = (
            self.db.query(User)
            .filter(
                func.lower(User.username) == normalized_username.lower(),
                User.user_id != user.user_id,
            )
            .first()
        )
        if existing:
            raise ValueError("El nombre de usuario ya está en uso.")
        user.username = normalized_username
        user.birth_date = birthDate
        user.gender = gender.strip().lower() if gender else None
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
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

    def _requirePasswordResetConfiguration(self) -> None:
        if len(self.passwordResetSecret) < 32:
            raise EmailDeliveryError(
                "El servicio de recuperación de contraseña no está configurado."
            )

    def _passwordResetFingerprint(self, namespace: str, value: str) -> str:
        return hmac.new(
            self.passwordResetSecret.encode("utf-8"),
            f"{namespace}:{value}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _hashPasswordResetToken(self, token: str) -> str:
        return self._passwordResetFingerprint("token", token)

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
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            self.passwordHashIterations,
        )
        return "$".join(
            (
                "pbkdf2_sha256",
                str(self.passwordHashIterations),
                base64.b64encode(salt).decode(),
                base64.b64encode(derived).decode(),
            )
        )

    def verifyPassword(self, password: str, passwordHash: str) -> bool:
        try:
            if passwordHash.startswith("pbkdf2_sha256$"):
                algorithm, iterations_text, salt_b64, derived_b64 = passwordHash.split("$")
                if algorithm != "pbkdf2_sha256":
                    return False
                iterations = int(iterations_text)
                if iterations < 100000 or iterations > 2000000:
                    return False
            else:
                salt_b64, derived_b64 = passwordHash.split(":")
                iterations = 120000
            salt = base64.b64decode(salt_b64.encode(), validate=True)
            expected = base64.b64decode(derived_b64.encode(), validate=True)
        except (ValueError, TypeError, binascii.Error):
            return False
        current = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(expected, current)

    def _passwordHashNeedsUpgrade(self, passwordHash: str) -> bool:
        try:
            algorithm, iterations_text, _, _ = passwordHash.split("$")
            return (
                algorithm != "pbkdf2_sha256"
                or int(iterations_text) < self.passwordHashIterations
            )
        except (ValueError, TypeError):
            return True
