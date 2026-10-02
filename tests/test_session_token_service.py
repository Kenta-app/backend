from datetime import datetime, timedelta, timezone
import json

from app.services.session_token_service import SessionTokenService
from app.serving.models import User


def test_session_token_rejects_tampering_and_password_changes(monkeypatch):
    monkeypatch.setenv(
        "AUTH_SESSION_SECRET", "test-session-secret-with-at-least-32-characters"
    )
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    service = SessionTokenService()
    user = User(user_id=7, username="test", email="test@example.com", password_hash="old-hash")

    token, max_age = service.issue(user, True)
    payload = service.verify(token)

    assert payload["uid"] == 7
    assert max_age == service.remember_ttl_days * 24 * 60 * 60
    assert service.verify(f"{token[:-1]}x") is None
    assert payload["pwd"] != service.password_fingerprint("new-hash")


def test_session_token_rejects_expired_payload(monkeypatch):
    monkeypatch.setenv(
        "AUTH_SESSION_SECRET", "test-session-secret-with-at-least-32-characters"
    )
    service = SessionTokenService()
    payload = {
        "uid": 3,
        "iat": 1,
        "exp": int((datetime.now(timezone.utc) - timedelta(seconds=1)).timestamp()),
        "pwd": "fingerprint",
        "nonce": "expired",
    }
    encoded = service._b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    token = f"{encoded}.{service._sign(encoded)}"
    assert service.verify(token) is None
