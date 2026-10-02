from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import secrets

from app.serving.models import User


class SessionTokenService:
    cookie_name = "kenta_session"

    def __init__(self, secret: str | None = None):
        self.secret = secret if secret is not None else (
            os.getenv("AUTH_SESSION_SECRET") or os.getenv("EMAIL_VERIFICATION_SECRET", "")
        )
        self.session_ttl_hours = int(os.getenv("AUTH_SESSION_TTL_HOURS", "12"))
        self.remember_ttl_days = int(os.getenv("AUTH_REMEMBER_TTL_DAYS", "30"))
        self.cookie_secure = os.getenv("AUTH_COOKIE_SECURE", "true").lower() in {
            "1", "true", "yes", "on"
        }

    def require_configuration(self) -> None:
        if len(self.secret) < 32:
            raise RuntimeError("AUTH_SESSION_SECRET debe tener al menos 32 caracteres.")

    def issue(self, user: User, remember: bool) -> tuple[str, int | None]:
        self.require_configuration()
        now = datetime.now(timezone.utc)
        ttl = (
            timedelta(days=self.remember_ttl_days)
            if remember
            else timedelta(hours=self.session_ttl_hours)
        )
        payload = {
            "uid": user.user_id,
            "iat": int(now.timestamp()),
            "exp": int((now + ttl).timestamp()),
            "pwd": self.password_fingerprint(user.password_hash),
            "nonce": secrets.token_urlsafe(8),
        }
        encoded = self._b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signature = self._sign(encoded)
        return f"{encoded}.{signature}", int(ttl.total_seconds()) if remember else None

    def verify(self, token: str) -> dict | None:
        if not token or len(self.secret) < 32:
            return None
        try:
            encoded, signature = token.split(".", 1)
            if not hmac.compare_digest(signature, self._sign(encoded)):
                return None
            payload = json.loads(self._b64decode(encoded))
            if int(payload.get("exp", 0)) <= int(datetime.now(timezone.utc).timestamp()):
                return None
            if int(payload.get("uid", 0)) <= 0:
                return None
            return payload
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
            return None

    def password_fingerprint(self, password_hash: str) -> str:
        self.require_configuration()
        return hmac.new(
            self.secret.encode("utf-8"),
            password_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:24]

    def _sign(self, encoded: str) -> str:
        digest = hmac.new(
            self.secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        return self._b64encode(digest)

    @staticmethod
    def _b64encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _b64decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(f"{value}{padding}")
