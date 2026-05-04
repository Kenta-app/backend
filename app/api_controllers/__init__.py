from app.api_controllers.admin_controller import router as admin_router
from app.api_controllers.auth_controller import router as auth_router
from app.api_controllers.interaction_controller import router as interaction_router
from app.api_controllers.news_controller import router as news_router
from app.api_controllers.pipeline_controller import router as pipeline_router

__all__ = [
    "admin_router",
    "auth_router",
    "interaction_router",
    "news_router",
    "pipeline_router",
]
