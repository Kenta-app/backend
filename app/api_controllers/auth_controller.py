from __future__ import annotations

from datetime import date
import re

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from app.api_controllers.base_controller import BaseController
from app.api_controllers.serializers import serialize_user
from app.application_services.auth_service import AuthService, EmailNotVerifiedError
from app.dependencies import get_auth_service, get_current_user, get_session_token_service
from app.services.email_service import EmailDeliveryError
from app.services.session_token_service import SessionTokenService
from app.serving.models import User

router = APIRouter(prefix="/auth", tags=["Auth"])


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    # Los campos de perfil se reciben desde la UI actual, pero son opcionales
    # para mantener compatibilidad con las cuentas creadas por clientes previos.
    birthDate: date | None = None
    gender: str | None = Field(default=None, min_length=1, max_length=50)
    acceptedTerms: bool
    termsVersion: str = Field(min_length=1, max_length=32)
    privacyPolicyVersion: str = Field(min_length=1, max_length=32)
    studyReminderOptIn: bool = False

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if any(ord(char) < 32 for char in normalized):
            raise ValueError("El nombre de usuario contiene caracteres inválidos.")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Ingresa un correo válido.")
        return normalized

    @field_validator("gender")
    @classmethod
    def normalize_gender(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower()

    @field_validator("birthDate")
    @classmethod
    def validate_birth_date(cls, value: date | None) -> date | None:
        if value is None:
            return None
        if value >= date.today():
            raise ValueError("La fecha de nacimiento debe ser anterior a hoy.")
        return value

    @field_validator("acceptedTerms")
    @classmethod
    def validate_terms_acceptance(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Debes aceptar los Términos de Servicio y la Política de Privacidad.")
        return value


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=1, max_length=128)
    remember: bool = False


class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str = Field(min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    email: str
    code: str = Field(pattern=r"^\d{6}$")


class ResendVerificationRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)


class ProfileUpdateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    birthDate: date | None = None
    gender: str | None = Field(default=None, min_length=1, max_length=50)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if any(ord(char) < 32 for char in normalized):
            raise ValueError("El nombre de usuario contiene caracteres inválidos.")
        return normalized

    @field_validator("gender")
    @classmethod
    def normalize_gender(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else None

    @field_validator("birthDate")
    @classmethod
    def validate_birth_date(cls, value: date | None) -> date | None:
        if value is not None and value >= date.today():
            raise ValueError("La fecha de nacimiento debe ser anterior a hoy.")
        return value


class AuthController(BaseController):
    def __init__(
        self,
        authService: AuthService,
        sessionService: SessionTokenService,
        current_user: User | None = None,
    ):
        super().__init__(current_user)
        self.authService = authService
        self.sessionService = sessionService

    def _setSessionCookie(
        self, response: Response, user: User, remember: bool = False
    ) -> None:
        try:
            token, max_age = self.sessionService.issue(user, remember)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        response.set_cookie(
            key=self.sessionService.cookie_name,
            value=token,
            max_age=max_age,
            httponly=True,
            secure=self.sessionService.cookie_secure,
            samesite="lax",
            path="/",
        )

    def postRegister(
        self,
        username: str,
        email: str,
        password: str,
        birthDate: date | None,
        gender: str | None,
        termsVersion: str,
        privacyPolicyVersion: str,
        studyReminderOptIn: bool,
    ) -> dict:
        try:
            user = self.authService.register(
                username,
                email,
                password,
                birthDate,
                gender,
                termsVersion,
                privacyPolicyVersion,
                studyReminderOptIn,
            )
        except EmailDeliveryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return self.successResponse(
            {"email": user.email, "verificationRequired": True}
        )

    def postLogin(
        self, response: Response, email: str, password: str, remember: bool
    ) -> dict:
        try:
            user = self.authService.login(email, password)
        except EmailNotVerifiedError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "EMAIL_NOT_VERIFIED",
                    "message": str(exc),
                    "email": email.strip().lower(),
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        self._setSessionCookie(response, user, remember)
        return self.successResponse(serialize_user(user))

    def postChangePassword(
        self, response: Response, currentPassword: str, newPassword: str
    ) -> dict:
        user = self.requireAuth()
        try:
            changed_user = self.authService.changePassword(user, currentPassword, newPassword)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        self._setSessionCookie(response, changed_user, False)
        return self.successResponse({"changed": True})

    def postVerifyEmail(self, response: Response, email: str, code: str) -> dict:
        try:
            user = self.authService.verifyEmail(email, code)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        self._setSessionCookie(response, user, False)
        return self.successResponse(serialize_user(user))

    def getMe(self) -> dict:
        return self.successResponse(serialize_user(self.requireAuth()))

    def patchProfile(
        self,
        username: str,
        birthDate: date | None,
        gender: str | None,
    ) -> dict:
        user = self.requireAuth()
        try:
            updated = self.authService.updateProfile(user, username, birthDate, gender)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return self.successResponse(serialize_user(updated))

    def postLogout(self, response: Response) -> dict:
        response.delete_cookie(
            key=self.sessionService.cookie_name,
            httponly=True,
            secure=self.sessionService.cookie_secure,
            samesite="lax",
            path="/",
        )
        return self.successResponse({"loggedOut": True})

    def postResendVerification(self, email: str) -> dict:
        try:
            self.authService.resendVerification(email)
        except EmailDeliveryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return self.successResponse({"email": email.strip().lower(), "verificationRequired": True})


def get_auth_controller(
    auth_service: AuthService = Depends(get_auth_service),
    session_service: SessionTokenService = Depends(get_session_token_service),
    current_user: User | None = Depends(get_current_user),
) -> AuthController:
    return AuthController(auth_service, session_service, current_user)


@router.post("/register")
def post_register(
    payload: RegisterRequest,
    controller: AuthController = Depends(get_auth_controller),
):
    return controller.postRegister(
        payload.username,
        payload.email,
        payload.password,
        payload.birthDate,
        payload.gender,
        payload.termsVersion,
        payload.privacyPolicyVersion,
        payload.studyReminderOptIn,
    )


@router.post("/login")
def post_login(
    payload: LoginRequest,
    response: Response,
    controller: AuthController = Depends(get_auth_controller),
):
    return controller.postLogin(response, payload.email, payload.password, payload.remember)


@router.post("/change-password")
def post_change_password(
    payload: ChangePasswordRequest,
    response: Response,
    controller: AuthController = Depends(get_auth_controller),
):
    return controller.postChangePassword(
        response, payload.currentPassword, payload.newPassword
    )


@router.post("/verify-email")
def post_verify_email(
    payload: VerifyEmailRequest,
    response: Response,
    controller: AuthController = Depends(get_auth_controller),
):
    return controller.postVerifyEmail(response, payload.email, payload.code)


@router.get("/me")
def get_me(controller: AuthController = Depends(get_auth_controller)):
    return controller.getMe()


@router.patch("/profile")
def patch_profile(
    payload: ProfileUpdateRequest,
    controller: AuthController = Depends(get_auth_controller),
):
    return controller.patchProfile(payload.username, payload.birthDate, payload.gender)


@router.post("/logout")
def post_logout(
    response: Response,
    controller: AuthController = Depends(get_auth_controller),
):
    return controller.postLogout(response)


@router.post("/resend-verification")
def post_resend_verification(
    payload: ResendVerificationRequest,
    controller: AuthController = Depends(get_auth_controller),
):
    return controller.postResendVerification(payload.email)
