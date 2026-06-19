"""
Controlador API para justificaciones de predicciones.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from app.api_controllers.base_controller import BaseController
from app.application_services.justification_service import GeminiJustificationService
from app.schemas.justification_schemas import (
    JustificationError,
    JustificationRequest,
    JustificationResponse,
)
from app.serving.models import User

logger = logging.getLogger(__name__)


class JustificationController(BaseController):
    """
    Controlador para operaciones de justificaci?n de predicciones.
    Maneja requests de generaci?n, recuperaci?n de cach? y limpieza.
    """

    def __init__(
        self,
        justification_service: GeminiJustificationService,
        current_user: Optional[User] = None,
    ):
        """
        Inicializa el controlador.

        Args:
            justification_service: Servicio de justificaci?n inyectado
            current_user: Usuario actual del contexto de request
        """
        super().__init__(current_user)
        self.justification_service = justification_service

    def generate_justification(self, request: JustificationRequest) -> dict:
        """
        Genera una justificaci?n para una predicci?n espec?fica.

        Args:
            request: JustificationRequest con prediction_id y opciones

        Returns:
            Respuesta exitosa con JustificationResponse

        Raises:
            HTTPException: En caso de errores de validaci?n o procesamiento
        """
        try:
            logger.info(
                f"Generando justificaci?n para predicci?n {request.prediction_id} "
                f"(regenerate={request.regenerate}, include_context={request.include_context})"
            )

            result = self.justification_service.generate_justification(
                prediction_id=request.prediction_id,
                include_context=request.include_context,
                regenerate=request.regenerate,
            )

            return self.successResponse(result)

        except ValueError as exc:
            logger.warning(f"Predicci?n no encontrada: {str(exc)}")
            raise HTTPException(
                status_code=404,
                detail=f"Predicci?n no encontrada: {str(exc)}",
            ) from exc

        except RuntimeError as exc:
            logger.error(f"Error al conectar con Gemini: {str(exc)}")
            raise HTTPException(
                status_code=503,
                detail="Servicio de justificaci?n no disponible. Intenta nuevamente m?s tarde.",
            ) from exc

        except Exception as exc:
            logger.error(f"Error inesperado en justificaci?n: {str(exc)}")
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor",
            ) from exc

    def get_justification(self, prediction_id: int) -> dict:
        """
        Obtiene la justificaci?n de una predicci?n (desde cach? si existe).

        Args:
            prediction_id: ID de la predicci?n

        Returns:
            Respuesta con JustificationResponse

        Raises:
            HTTPException: Si la predicci?n no existe o hay error
        """
        try:
            request = JustificationRequest(
                prediction_id=prediction_id,
                include_context=True,
                regenerate=False,
            )
            return self.generate_justification(request)

        except HTTPException:
            raise

        except Exception as exc:
            logger.error(f"Error al obtener justificaci?n: {str(exc)}")
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor",
            ) from exc

    def clear_cache(self, prediction_id: Optional[int] = None) -> dict:
        """
        Limpia el cach? de justificaciones.

        Args:
            prediction_id: ID espec?fico a limpiar, o None para limpiar

        Returns:
            Respuesta con estad?sticas de limpieza

        Raises:
            HTTPException: En caso de error
        """
        try:
            logger.info(
                f"Limpiando cach? de justificaciones (prediction_id={prediction_id})"
            )

            stats = self.justification_service.clear_cache(prediction_id)
            return self.successResponse(stats)

        except Exception as exc:
            logger.error(f"Error al limpiar cach?: {str(exc)}")
            raise HTTPException(
                status_code=500,
                detail="Error al limpiar cach?",
            ) from exc

    def get_cache_stats(self) -> dict:
        """
        Obtiene estad?sticas del cach?.

        Returns:
            Respuesta con estad?sticas de uso

        Raises:
            HTTPException: En caso de error
        """
        try:
            stats = self.justification_service.get_cache_stats()
            return self.successResponse(stats)

        except Exception as exc:
            logger.error(f"Error al obtener estad?sticas: {str(exc)}")
            raise HTTPException(
                status_code=500,
                detail="Error al obtener estad?sticas",
            ) from exc

