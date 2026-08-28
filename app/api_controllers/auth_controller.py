from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.api_controllers.base_controller import BaseController
from app.api_controllers.serializers import serialize_user
from app.application_services.auth_service import AuthService, EmailNotVerifiedError
from app.dependencies import get_auth_service, get_current_user
from app.services.email_service import EmailDeliveryError
from app.serving.models import User

router = APIRouter(prefix="/auth", tags=["Auth"])


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    # Los campos de perfil se reciben desde la UI actual, pero son opcionales
    # para mantener compatibilidad con las cuentas creadas por clientes previos.
    birthDate: date | None = None
    gender: str | None = Field(default=None, min_length=1, max_length=50)
    acceptedTerms: bool
    termsVersion: str = Field(min_length=1, max_length=32)
    privacyPolicyVersion: str = Field(min_length=1, max_length=32)

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
    email: str
    password: str


class VerifyEmailRequest(BaseModel):
    email: str
    code: str = Field(pattern=r"^\d{6}$")


class ResendVerificationRequest(BaseModel):
    email: str


class AuthController(BaseController):
    def __init__(self, authService: AuthService, current_user: User | None = None):
        super().__init__(current_user)
        self.authService = authService

    def postRegister(
        self,
        username: str,
        email: str,
        password: str,
        birthDate: date | None,
        gender: str | None,
        termsVersion: str,
        privacyPolicyVersion: str,
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
            )
        except EmailDeliveryError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return self.successResponse(
            {"email": user.email, "verificationRequired": True}
        )

    def postLogin(self, email: str, password: str) -> dict:
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
        return self.successResponse(serialize_user(user))

    def postVerifyEmail(self, email: str, code: str) -> dict:
        try:
            user = self.authService.verifyEmail(email, code)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return self.successResponse(serialize_user(user))

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
    current_user: User | None = Depends(get_current_user),
) -> AuthController:
    return AuthController(auth_service, current_user)


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
    )


@router.post("/login")
def post_login(
    payload: LoginRequest,
    controller: AuthController = Depends(get_auth_controller),
):
    return controller.postLogin(payload.email, payload.password)


@router.post("/verify-email")
def post_verify_email(
    payload: VerifyEmailRequest,
    controller: AuthController = Depends(get_auth_controller),
):
    return controller.postVerifyEmail(payload.email, payload.code)


@router.post("/resend-verification")
def post_resend_verification(
    payload: ResendVerificationRequest,
    controller: AuthController = Depends(get_auth_controller),
):
    return controller.postResendVerification(payload.email)
