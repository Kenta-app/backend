from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api_controllers.base_controller import BaseController
from app.api_controllers.serializers import serialize_click, serialize_reaction, serialize_view
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
