from datetime import timedelta
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application_services.auth_service import AuthService, EmailNotVerifiedError
from app.db.database import apply_sqlite_schema_translation
from app.serving.models import User


class FakeEmailSender:
    def __init__(self):
        self.messages = []

    def sendVerificationCode(self, email: str, code: str) -> None:
        self.messages.append({"email": email, "code": code})


class EmailVerificationTests(unittest.TestCase):
    def setUp(self):
        self.engine = apply_sqlite_schema_translation(
            create_engine("sqlite:///:memory:")
        )
        User.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.emailSender = FakeEmailSender()
        self.service = AuthService(
            self.db,
            self.emailSender,
            verificationSecret="test-verification-secret",
        )

    def tearDown(self):
        self.db.close()
        User.__table__.drop(self.engine)
        self.engine.dispose()

    def test_register_verify_and_login(self):
        user = self.service.register(
            "alice",
            "Alice@Example.com",
            "correct-horse-battery-staple",
            termsVersion="2026-08-28",
            privacyPolicyVersion="2026-08-28",
        )

        self.assertEqual(user.email, "alice@example.com")
        self.assertIsNone(user.email_verified_at)
        self.assertNotEqual(
            user.email_verification_code_hash,
            self.emailSender.messages[-1]["code"],
        )
        self.assertEqual(user.terms_version, "2026-08-28")

        with self.assertRaises(EmailNotVerifiedError):
            self.service.login("alice@example.com", "correct-horse-battery-staple")

        with self.assertRaises(ValueError):
            self.service.verifyEmail("alice@example.com", "000000")

        user.email_verification_sent_at -= timedelta(seconds=61)
        self.db.commit()
        self.service.resendVerification("alice@example.com")
        self.assertEqual(len(self.emailSender.messages), 2)

        verified = self.service.verifyEmail(
            "alice@example.com",
            self.emailSender.messages[-1]["code"],
        )
        self.assertIsNotNone(verified.email_verified_at)
        self.assertEqual(
            self.service.login("ALICE@example.com", "correct-horse-battery-staple").user_id,
            user.user_id,
        )


if __name__ == "__main__":
    unittest.main()
