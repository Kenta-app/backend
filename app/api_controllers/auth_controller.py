from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.api_controllers.base_controller import BaseController
from app.api_controllers.serializers import serialize_user
from app.application_services.auth_service import AuthService
from app.dependencies import get_auth_service, get_current_user
from app.serving.models import User

router = APIRouter(prefix="/auth", tags=["Auth"])


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    birthDate: date
    gender: str = Field(min_length=1, max_length=50)

    @field_validator("gender")
    @classmethod
    def normalize_gender(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("birthDate")
    @classmethod
    def validate_birth_date(cls, value: date) -> date:
        if value >= date.today():
            raise ValueError("La fecha de nacimiento debe ser anterior a hoy.")
        return value


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthController(BaseController):
    def __init__(self, authService: AuthService, current_user: User | None = None):
        super().__init__(current_user)
        self.authService = authService

    def postRegister(
        self,
        username: str,
        email: str,
        password: str,
        birthDate: date,
        gender: str,
    ) -> dict:
        try:
            user = self.authService.register(
                username,
                email,
                password,
                birthDate,
                gender,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return self.successResponse(serialize_user(user))

    def postLogin(self, username: str, password: str) -> dict:
        try:
            user = self.authService.login(username, password)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return self.successResponse(serialize_user(user))


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
    )


@router.post("/login")
def post_login(
    payload: LoginRequest,
    controller: AuthController = Depends(get_auth_controller),
):
    return controller.postLogin(payload.username, payload.password)
