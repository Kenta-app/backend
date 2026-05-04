from __future__ import annotations

import base64
import hashlib
import hmac
import os

from sqlalchemy.orm import Session

from app.serving.models import User


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def register(self, username: str, email: str, password: str) -> User:
        existing = (
            self.db.query(User)
            .filter((User.username == username) | (User.email == email))
            .first()
        )
        if existing:
            raise ValueError("El usuario o email ya existe.")

        user = User(
            username=username,
            email=email,
            password_hash=self.hashPassword(password),
            role="user",
        )
        user.register()
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def login(self, email: str, password: str) -> User:
        user = self.db.query(User).filter(User.email == email).first()
        if not user or not self.verifyPassword(password, user.password_hash):
            raise ValueError("Credenciales invalidas.")
        return user

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
