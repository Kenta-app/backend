"""
Router para endpoints de justificaci?n de predicciones.
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
        justification_service: Servicio de justificaci?n
        current_user: Usuario actual del contexto

    Returns:
        Instancia del controlador
    """
    return JustificationController(justification_service, current_user)


@router.post("/generate", summary="Generar justificaci?n para una predicci?n")
def generate_justification(
    request: JustificationRequest,
    controller: JustificationController = Depends(get_justification_controller),
) -> dict:
    """
    Genera una justificaci?n para una predicci?n espec?fica.

    **Request Body:**
    - `prediction_id` (int, requerido): ID de la predicci?n a justificar
    - `include_context` (bool, default=True): Incluir contexto del art?culo
    - `regenerate` (bool, default=False): Forzar regeneraci?n sin usar cach?

    **Responses:**
    - 200: Justificaci?n generada exitosamente
    - 404: Predicci?n no encontrada
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


@router.get("/{prediction_id}", summary="Obtener justificaci?n de una predicci?n")
def get_justification(
    prediction_id: int = Path(..., description="ID de la predicci?n"),
    controller: JustificationController = Depends(get_justification_controller),
) -> dict:
    """
    Obtiene la justificaci?n de una predicci?n (desde cach? si existe).

    **Path Parameters:**
    - `prediction_id` (int): ID de la predicci?n

    **Responses:**
    - 200: Justificaci?n obtenida (desde cach? o generada)
    - 404: Predicci?n no encontrada
    - 503: Servicio no disponible
    - 500: Error interno del servidor
    """
    return controller.get_justification(prediction_id)


@router.delete("/cache", summary="Limpiar cach? de justificaciones")
def clear_cache(
    prediction_id: Optional[int] = Query(
        default=None,
        description="ID espec?fico a limpiar. Si es None, limpia todo el cach?",
    ),
    controller: JustificationController = Depends(get_justification_controller),
) -> dict:
    """
    Limpia el cach? de justificaciones.

    **Query Parameters:**
    - `prediction_id` (int, opcional): ID espec?fico a limpiar, o None

    **Responses:**
    - 200: Cach? limpiado exitosamente
    - 500: Error al limpiar cach?

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


@router.get("/stats/cache", summary="Obtener estad?sticas del cach?")
def get_cache_stats(
    controller: JustificationController = Depends(get_justification_controller),
) -> dict:
    """
    Obtiene estad?sticas de uso del cach? de justificaciones.

    **Responses:**
    - 200: Estad?sticas obtenidas

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

