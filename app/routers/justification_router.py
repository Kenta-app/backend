"""
Router para endpoints de justificación de predicciones.
Define los endpoints POST, GET y DELETE para justificaciones.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.api_controllers.justification_controller import JustificationController
from app.dependencies import get_current_user, get_justification_service
from app.schemas.justification_schemas import JustificationRequest
from app.application_services.justification_service import GeminiJustificationService
from app.serving.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/justifications", tags=["Justifications"])


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


@router.post("/generate", summary="Generar justificación para una predicción")
def generate_justification(
    request: JustificationRequest,
    controller: JustificationController = Depends(get_justification_controller),
) -> dict:
    """
    Genera una justificación para una predicción específica.

    **Request Body:**
    - `prediction_id` (int, requerido): ID de la predicción a justificar
    - `include_context` (bool, default=True): Incluir contexto del artículo
    - `regenerate` (bool, default=False): Forzar regeneración sin usar caché

    **Responses:**
    - 200: Justificación generada exitosamente
    - 404: Predicción no encontrada
    - 503: Servicio de Gemini no disponible
    - 500: Error interno del servidor

    **Ejemplo de uso:**
    ```json
    {
        "prediction_id": 42,
        "include_context": true,
        "regenerate": false
    }
    ```
    """
    return controller.generate_justification(request)


@router.get("/{prediction_id}", summary="Obtener justificación de una predicción")
def get_justification(
    prediction_id: int = Path(..., description="ID de la predicción"),
    controller: JustificationController = Depends(get_justification_controller),
) -> dict:
    """
    Obtiene la justificación de una predicción (desde caché si existe).

    **Path Parameters:**
    - `prediction_id` (int): ID de la predicción

    **Responses:**
    - 200: Justificación obtenida (desde caché o generada)
    - 404: Predicción no encontrada
    - 503: Servicio no disponible
    - 500: Error interno del servidor
    """
    return controller.get_justification(prediction_id)


@router.delete("/cache", summary="Limpiar caché de justificaciones")
def clear_cache(
    prediction_id: Optional[int] = Query(
        default=None,
        description="ID específico a limpiar. Si es None, limpia todo el caché",
    ),
    controller: JustificationController = Depends(get_justification_controller),
) -> dict:
    """
    Limpia el caché de justificaciones.

    **Query Parameters:**
    - `prediction_id` (int, opcional): ID específico a limpiar, o None

    **Responses:**
    - 200: Caché limpiado exitosamente
    - 500: Error al limpiar caché

    **Ejemplo de respuesta:**
    ```json
    {
        "success": true,
        "data": {
            "cleared": 5,
            "total_cleared": 5,
            "cache_size": 15
        }
    }
    ```
    """
    return controller.clear_cache(prediction_id)


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

