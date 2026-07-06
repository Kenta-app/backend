"""
Interfaz del servicio de justificación de predicciones.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class IJustificationService(ABC):
    """
    Interfaz para servicios de justificación de predicciones.
    Define el contrato que deben cumplir las implementaciones.
    """

    @abstractmethod
    def generate_justification(
        self,
        prediction_id: int,
        include_context: bool = True,
        regenerate: bool = False,
    ) -> dict:
        """
        Genera una justificación para una predicción.

        Args:
            prediction_id: ID de la predicción a justificar
            include_context: Incluir contexto adicional del artículo
            regenerate: Forzar regeneración ignorando caché

        Returns:
            Diccionario con la justificación y metadatos

        Raises:
            ValueError: Si la predicción no existe
            RuntimeError: Si hay error al conectar con la API
        """
        pass

    @abstractmethod
    def clear_cache(self, prediction_id: Optional[int] = None) -> dict:
        """
        Limpia el caché de justificaciones.

        Args:
            prediction_id: ID específico a limpiar, o None para limpiar

        Returns:
            Diccionario con estadísticas de limpieza
        """
        pass

    @abstractmethod
    def get_cache_stats(self) -> dict:
        """
        Obtiene estadísticas del caché.

        Returns:
            Diccionario con métricas del caché
        """
        pass

