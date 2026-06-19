"""
Esquemas Pydantic para el servicio de justificaci?n de predicciones con Gemini.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class JustificationRequest(BaseModel):
    """
    Request para generar justificaci?n de una predicci?n.
    """

    prediction_id: int = Field(..., description="ID de la predicci?n a justificar")
    include_context: bool = Field(
        default=True,
        description="Incluir contexto adicional del art?culo en la justificaci?n",
    )
    regenerate: bool = Field(
        default=False,
        description="Forzar regeneraci?n ignorando cach?",
    )


class EvidenceSource(BaseModel):
    """
    Fuente period?stica o verificador de hechos usado como evidencia.
    """

    url: str = Field(..., description="URL directa de la fuente period?stica")
    source: str = Field(..., description="Nombre del medio o verificador")
    title: str = Field(..., description="T?tulo del art?culo")
    excerpt: str = Field(..., description="Extracto relevante del art?culo")


class SupportingSource(BaseModel):
    """
    Referencia breve incluida en el resumen de verificaci?n.
    """

    source: str = Field(..., description="Nombre del medio o verificador")
    title: str = Field(..., description="T?tulo del art?culo")


class VerificationSummary(BaseModel):
    """
    S?ntesis impersonal basada solo en fuentes period?sticas verificables.
    """

    supporting_sources: list[SupportingSource] = Field(
        default_factory=list,
        description="Fuentes confiables que respaldan la conclusi?n",
    )
    conclusion: str = Field(..., description="Conclusi?n impersonal basada en evidencia")


class MlPredictionSummary(BaseModel):
    """
    Resultado del modelo ML separado de la evidencia period?stica.
    """

    fake_score: float = Field(..., description="Puntuaci?n de falsedad (0-1)")
    sentiment_label: Optional[str] = Field(
        default=None,
        description="Etiqueta de sentimiento/postura",
    )


class JustificationResponse(BaseModel):
    """
    Response con el informe de evidencia generado.
    """

    prediction_id: int = Field(..., description="ID de la predicci?n justificada")
    sources: list[EvidenceSource] = Field(default_factory=list)
    verification_summary: VerificationSummary
    ml_prediction: MlPredictionSummary = Field(
        ...,
        description="Salida del modelo ML, separada de la evidencia encontrada",
    )
    from_cache: bool = Field(
        default=False,
        description="Indica si la justificaci?n proviene de cach?",
    )
    generated_at: datetime = Field(..., description="Timestamp de generaci?n")
    model_used: str = Field(
        default="gemini-2.5-flash",
        description="Modelo de Gemini utilizado",
    )


class JustificationError(BaseModel):
    """
    Response en caso de error.
    """

    error: str = Field(..., description="Mensaje de error")
    error_code: str = Field(..., description="C?digo del error")
    retry_after: Optional[int] = Field(
        default=None,
        description="Segundos a esperar antes de reintentar (en caso de rate limit)",
    )
    prediction_id: Optional[int] = Field(default=None, description="ID de la predicci?n")

