from __future__ import annotations

from fastapi import HTTPException

from app.serving.models import User


class BaseController:
    def __init__(self, current_user: User | None = None):
        self._current_user = current_user

    def getCurrentUser(self) -> User | None:
        return self._current_user

    def requireAuth(self) -> User:
        user = self.getCurrentUser()
        if not user:
            raise HTTPException(status_code=401, detail="Autenticacion requerida.")
        return user

    def requireRole(self, role: str) -> User:
        user = self.requireAuth()
        if user.role != role and not (role == "admin" and user.canModerate()):
            raise HTTPException(status_code=403, detail="Permisos insuficientes.")
        return user

    def successResponse(self, data: object) -> dict:
        return {"success": True, "data": data}

    def errorResponse(self, message: str, code: int) -> dict:
        return {"success": False, "error": {"message": message, "code": code}}

    def paginate(self, items: list, page: int, pageSize: int) -> dict:
        return {
            "items": items,
            "page": page,
            "pageSize": pageSize,
            "count": len(items),
        }
