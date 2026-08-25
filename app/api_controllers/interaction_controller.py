from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.api_controllers.base_controller import BaseController
from app.api_controllers.serializers import (
    serialize_click,
    serialize_detail_click,
    serialize_reaction,
    serialize_session,
    serialize_view,
)
from app.application_services.interaction_service import InteractionService
from app.dependencies import get_current_user, get_interaction_service
from app.serving.models import User

router = APIRouter(prefix="/interactions", tags=["Interactions"])


class ReactionRequest(BaseModel):
    newsId: int
    reaction: int


class ViewRequest(BaseModel):
    newsId: int
    timeSpentSec: int


class ClickRequest(BaseModel):
    newsId: int


class DetailClickRequest(BaseModel):
    newsId: int


class SessionRequest(BaseModel):
    timeSpentSec: int
    startedAt: datetime | None = None


class InteractionEventRequest(BaseModel):
    type: Literal["view", "click", "detail-click", "session"]
    newsId: int | None = Field(default=None, gt=0)
    timeSpentSec: int | None = Field(default=None, ge=0)
    startedAt: datetime | None = None

    @model_validator(mode="after")
    def validate_fields(self):
        if self.type in {"view", "click", "detail-click"} and self.newsId is None:
            raise ValueError("newsId es obligatorio para este tipo de evento.")
        if self.type in {"view", "session"} and self.timeSpentSec is None:
            raise ValueError("timeSpentSec es obligatorio para este tipo de evento.")
        return self


class InteractionBatchRequest(BaseModel):
    events: list[InteractionEventRequest] = Field(min_length=1, max_length=100)


class InteractionController(BaseController):
    def __init__(self, interactionService: InteractionService, current_user: User | None = None):
        super().__init__(current_user)
        self.interactionService = interactionService

    def postReaction(self, newsId: int, reaction: int) -> dict:
        user = self.requireAuth()
        item = self.interactionService.recordReaction(user.user_id, newsId, reaction)
        return self.successResponse(serialize_reaction(item))

    def deleteReaction(self, newsId: int) -> dict:
        user = self.requireAuth()
        self.interactionService.removeReaction(user.user_id, newsId)
        return self.successResponse({"newsId": newsId, "removed": True})

    def postView(self, newsId: int, timeSpentSec: int) -> dict:
        user = self.requireAuth()
        item = self.interactionService.recordView(user.user_id, newsId, timeSpentSec)
        return self.successResponse(serialize_view(item))

    def postClick(self, newsId: int) -> dict:
        user = self.requireAuth()
        item = self.interactionService.recordClick(user.user_id, newsId)
        return self.successResponse(serialize_click(item))

    def postDetailClick(self, newsId: int) -> dict:
        user = self.requireAuth()
        item = self.interactionService.recordDetailClick(user.user_id, newsId)
        return self.successResponse(serialize_detail_click(item))

    def postSession(self, timeSpentSec: int, startedAt: datetime | None = None) -> dict:
        user = self.requireAuth()
        try:
            item = self.interactionService.recordSession(user.user_id, timeSpentSec, startedAt)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return self.successResponse(serialize_session(item))

    def postBatch(self, events: list[InteractionEventRequest]) -> dict:
        user = self.requireAuth()
        if user.canModerate():
            return self.successResponse(
                {"ignored": True, "reason": "staff_user", "total": 0}
            )

        counts = self.interactionService.recordBatch(
            user.user_id,
            [event.model_dump() for event in events],
        )
        return self.successResponse({"ignored": False, **counts})


def get_interaction_controller(
    interaction_service: InteractionService = Depends(get_interaction_service),
    current_user: User | None = Depends(get_current_user),
) -> InteractionController:
    return InteractionController(interaction_service, current_user)


@router.post("/reaction")
def post_reaction(
    payload: ReactionRequest,
    controller: InteractionController = Depends(get_interaction_controller),
):
    return controller.postReaction(payload.newsId, payload.reaction)


@router.delete("/reaction/{news_id}")
def delete_reaction(
    news_id: int,
    controller: InteractionController = Depends(get_interaction_controller),
):
    return controller.deleteReaction(news_id)


@router.post("/view")
def post_view(
    payload: ViewRequest,
    controller: InteractionController = Depends(get_interaction_controller),
):
    return controller.postView(payload.newsId, payload.timeSpentSec)


@router.post("/click")
def post_click(
    payload: ClickRequest,
    controller: InteractionController = Depends(get_interaction_controller),
):
    return controller.postClick(payload.newsId)


@router.post("/detail-click")
def post_detail_click(
    payload: DetailClickRequest,
    controller: InteractionController = Depends(get_interaction_controller),
):
    return controller.postDetailClick(payload.newsId)


@router.post("/session")
def post_session(
    payload: SessionRequest,
    controller: InteractionController = Depends(get_interaction_controller),
):
    return controller.postSession(payload.timeSpentSec, payload.startedAt)


@router.post("/batch")
def post_batch(
    payload: InteractionBatchRequest,
    controller: InteractionController = Depends(get_interaction_controller),
):
    return controller.postBatch(payload.events)
