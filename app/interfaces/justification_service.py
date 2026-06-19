"""
Interfaz del servicio de justificaci?n de predicciones.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class IJustificationService(ABC):
    """
    Interfaz para servicios de justificaci?n de predicciones.
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
        Genera una justificaci?n para una predicci?n.

        Args:
            prediction_id: ID de la predicci?n a justificar
            include_context: Incluir contexto adicional del art?culo
            regenerate: Forzar regeneraci?n ignorando cach?

        Returns:
            Diccionario con la justificaci?n y metadatos

        Raises:
            ValueError: Si la predicci?n no existe
            RuntimeError: Si hay error al conectar con la API
        """
        pass

    @abstractmethod
    def clear_cache(self, prediction_id: Optional[int] = None) -> dict:
        """
        Limpia el cach? de justificaciones.

        Args:
            prediction_id: ID espec?fico a limpiar, o None para limpiar

        Returns:
            Diccionario con estad?sticas de limpieza
        """
        pass

    @abstractmethod
    def get_cache_stats(self) -> dict:
        """
        Obtiene estad?sticas del cach?.

        Returns:
            Diccionario con m?tricas del cach?
        """
        pass

