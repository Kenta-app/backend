from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api_controllers.base_controller import BaseController
from app.application_services.draw_service import (
    DrawAlreadyConfirmedError,
    DrawConfirmationError,
    DrawService,
)
from app.dependencies import get_current_user, get_draw_service
from app.serving.models import User

router = APIRouter(prefix="/draw", tags=["Draw"])


class DrawConfirmationRequest(BaseModel):
    drawId: str = Field(min_length=1, max_length=100)


class DrawController(BaseController):
    def __init__(self, drawService: DrawService, current_user: User | None = None):
        super().__init__(current_user)
        self.drawService = drawService

    def postConfirmRead(self, drawId: str) -> dict:
        user = self.requireAuth()
        try:
            self.drawService.confirmRead(user, drawId)
        except DrawAlreadyConfirmedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except DrawConfirmationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return self.successResponse({"confirmed": True})


def get_draw_controller(
    draw_service: DrawService = Depends(get_draw_service),
    current_user: User | None = Depends(get_current_user),
) -> DrawController:
    return DrawController(draw_service, current_user)


@router.post("/confirm-read")
def post_confirm_read(
    payload: DrawConfirmationRequest,
    controller: DrawController = Depends(get_draw_controller),
):
    return controller.postConfirmRead(payload.drawId)
