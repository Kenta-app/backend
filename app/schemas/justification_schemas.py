"""
Esquemas Pydantic para el servicio de justificación de predicciones con Gemini.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class JustificationRequest(BaseModel):
    """
    Request para generar justificación de una predicción.
    """

    prediction_id: int = Field(..., description="ID de la predicción a justificar")
    include_context: bool = Field(
        default=True,
        description="Incluir contexto adicional del artículo en la justificación",
    )
    regenerate: bool = Field(
        default=False,
        description="Forzar regeneración ignorando caché",
    )


class EvidenceSource(BaseModel):
    """
    Fuente periodística o verificador de hechos usado como evidencia.
    """

    url: str = Field(..., description="URL directa de la fuente periodística")
    source: str = Field(..., description="Nombre del medio o verificador")
    title: str = Field(..., description="Título del artículo")
    excerpt: str = Field(..., description="Extracto relevante del artículo")
    claim: Optional[str] = Field(default=None, description="Afirmación central evaluada")
    evidenceStance: str = Field(
        default="discusses",
        description="Relación: supports, refutes, discusses o unrelated",
    )
    relevanceScore: Optional[float] = Field(default=None, ge=0, le=1)
    independenceKey: Optional[str] = Field(default=None)
    assessmentMethod: str = Field(default="legacy_related_source")
    assessmentVersion: str = Field(default="evidence-policy-2026-10-25-v5")
    sourceRole: str = Field(default="independent_evidence")
    independenceEligible: bool = True


class EvidenceAssessment(BaseModel):
    status: str = Field(
        ...,
        description="supported, disputed, mixed o insufficient_evidence",
    )
    supportingSources: int = 0
    refutingSources: int = 0
    contextualSources: int = 0
    unrelatedSources: int = 0
    primaryContextSources: int = 0
    totalSourceRecords: int = 0
    distinctPublisherSources: int = 0
    minimumDistinctPublisherAgreement: int = 2
    independenceStatus: str = "publisher_domain_only"
    assessmentVersion: str


class SupportingSource(BaseModel):
    """
    Referencia breve incluida en el resumen de verificación.
    """

    source: str = Field(..., description="Nombre del medio o verificador")
    title: str = Field(..., description="Título del artículo")


class VerificationSummary(BaseModel):
    """
    Síntesis impersonal basada solo en fuentes periodísticas verificables.
    """

    supporting_sources: list[SupportingSource] = Field(
        default_factory=list,
        description="Fuentes confiables que respaldan la conclusión",
    )
    conclusion: str = Field(..., description="Conclusión impersonal basada en evidencia")


class MlPredictionSummary(BaseModel):
    """
    Resultado del modelo ML separado de la evidencia periodística.
    """

    fake_score: Optional[float] = Field(
        default=None,
        description="Puntuación interna de falsedad (0-1), omitida si la política pública la retiene",
    )
    analysis_status: str = Field(default="available")
    sentiment_label: Optional[str] = Field(
        default=None,
        description="Etiqueta de sentimiento/postura",
    )


class JustificationResponse(BaseModel):
    """
    Response con el informe de evidencia generado.
    """

    prediction_id: int = Field(..., description="ID de la predicción justificada")
    sources: list[EvidenceSource] = Field(default_factory=list)
    evidence_assessment: EvidenceAssessment
    verification_summary: VerificationSummary
    ml_prediction: MlPredictionSummary = Field(
        ...,
        description="Salida del modelo ML, separada de la evidencia encontrada",
    )
    from_cache: bool = Field(
        default=False,
        description="Indica si la justificación proviene de caché",
    )
    generated_at: datetime = Field(..., description="Timestamp de generación")
    model_used: str = Field(
        default="gemini-2.5-flash",
        description="Modelo de Gemini utilizado",
    )


class JustificationError(BaseModel):
    """
    Response en caso de error.
    """

    error: str = Field(..., description="Mensaje de error")
    error_code: str = Field(..., description="Código del error")
    retry_after: Optional[int] = Field(
        default=None,
        description="Segundos a esperar antes de reintentar (en caso de rate limit)",
    )
    prediction_id: Optional[int] = Field(default=None, description="ID de la predicción")

