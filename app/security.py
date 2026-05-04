from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone

import bcrypt


JWT_SECRET = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXP_HOURS = int(os.getenv("JWT_EXP_HOURS", "24"))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, expires_hours: int = JWT_EXP_HOURS) -> str:
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    payload = {
        "sub": subject,
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=expires_hours)).timestamp()),
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }
    encoded_header = _urlsafe_b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign(f"{encoded_header}.{encoded_payload}")
    return f"{encoded_header}.{encoded_payload}.{signature}"


def decode_access_token(token: str) -> dict:
    try:
        encoded_header, encoded_payload, signature = token.split(".")
    except ValueError as exc:
        raise ValueError("Token JWT invalido.") from exc

    expected_signature = _sign(f"{encoded_header}.{encoded_payload}")
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("Token JWT invalido.")

    payload = json.loads(_urlsafe_b64decode(encoded_payload))
    exp = payload.get("exp")
    if exp is None or int(exp) < int(datetime.now(timezone.utc).timestamp()):
        raise ValueError("Token expirado.")
    return payload


def _sign(message: str) -> str:
    signature = hmac.new(JWT_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return _urlsafe_b64encode(signature)


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("utf-8")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("utf-8"))
