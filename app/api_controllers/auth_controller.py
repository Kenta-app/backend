from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

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


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthController(BaseController):
    def __init__(self, authService: AuthService, current_user: User | None = None):
        super().__init__(current_user)
        self.authService = authService

    def postRegister(self, username: str, email: str, password: str) -> dict:
        try:
            user = self.authService.register(username, email, password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return self.successResponse(serialize_user(user))

    def postLogin(self, email: str, password: str) -> dict:
        try:
            user = self.authService.login(email, password)
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
    return controller.postRegister(payload.username, payload.email, payload.password)


@router.post("/login")
def post_login(
    payload: LoginRequest,
    controller: AuthController = Depends(get_auth_controller),
):
    return controller.postLogin(payload.email, payload.password)
