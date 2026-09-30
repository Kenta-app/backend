"""
Router para endpoints de justificación de predicciones.
Define los endpoints POST, GET y DELETE para justificaciones.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Path

from app.api_controllers.justification_controller import JustificationController
from app.dependencies import get_current_user, get_justification_service
from app.application_services.justification_service import GeminiJustificationService
from app.serving.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/justifications", tags=["Justifications"])

# Deliberately expose read-only endpoints. The current X-User-Id header is not
# authentication, so generation and deletion must remain CLI-only until a
# server-verified moderator credential is implemented.


def get_justification_controller(
    justification_service: GeminiJustificationService = Depends(get_justification_service),
    current_user: Optional[User] = Depends(get_current_user),
) -> JustificationController:
    """
    Dependency injection del controlador de justificaciones.

    Args:
        justification_service: Servicio de justificación
        current_user: Usuario actual del contexto

    Returns:
        Instancia del controlador
    """
    return JustificationController(justification_service, current_user)


@router.get("/stats/cache", summary="Obtener estadísticas del caché")
def get_cache_stats(
    controller: JustificationController = Depends(get_justification_controller),
) -> dict:
    """
    Obtiene estadísticas de uso del caché de justificaciones.

    **Responses:**
    - 200: Estadísticas obtenidas

    **Ejemplo de respuesta:**
    ```json
    {
        "success": true,
        "data": {
            "cache_size": 20,
            "cache_max_size": 1000,
            "cache_ttl": 3600,
            "hits": 150,
            "misses": 50,
            "total_requests": 200,
            "hit_rate": "75.00%",
            "model": "gemini-1.5-flash",
            "max_retries": 3
        }
    }
    ```
    """
    return controller.get_cache_stats()


@router.get("/news/{news_id}", summary="Obtener fuentes guardadas de una noticia")
def get_news_justification(
    news_id: int = Path(..., description="ID de la noticia publicada"),
    controller: JustificationController = Depends(get_justification_controller),
) -> dict:
    """
    Obtiene fuentes relacionadas ya guardadas para una noticia publicada.
    Este endpoint no invoca Gemini ni genera costos nuevos.
    """
    return controller.get_news_justification(news_id)


@router.get("/{prediction_id}", summary="Obtener fuentes guardadas de una predicción")
def get_justification(
    prediction_id: int = Path(..., description="ID de la predicción"),
    controller: JustificationController = Depends(get_justification_controller),
) -> dict:
    """
    Obtiene fuentes relacionadas ya guardadas para una predicción.
    Este endpoint no invoca Gemini ni genera costos nuevos.
    """
    return controller.get_justification(prediction_id)

