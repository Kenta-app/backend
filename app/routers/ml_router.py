from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.ml.pipeline import ModelNotReadyError, news_analysis_pipeline
from app.dependencies import get_current_user
from app.serving.models import User

router = APIRouter()


class NewsAnalysisRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=500)
    content: Optional[str] = Field(default=None, max_length=50_000)
    text: Optional[str] = Field(default=None, max_length=50_000)
    include_summary: bool = True
    force_summary: bool = False

    @model_validator(mode="after")
    def validate_payload(self):
        if not any([self.title, self.content, self.text]):
            raise ValueError("Debes enviar title, content o text para analizar.")
        return self


class TextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)


def require_ml_operator(current_user: User | None = Depends(get_current_user)) -> User:
    if not current_user:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    if not current_user.canModerate():
        raise HTTPException(status_code=403, detail="Permisos insuficientes.")
    return current_user


@router.get("/health")
def ml_health():
    return news_analysis_pipeline.get_status()


@router.post("/analyze")
def analyze_news(
    request: NewsAnalysisRequest,
    _operator: User = Depends(require_ml_operator),
):
    try:
        return news_analysis_pipeline.analyze_news(
            title=request.title,
            content=request.content,
            text=request.text,
            include_summary=request.include_summary,
            force_summary=request.force_summary,
            allow_partial=True,
        )
    except ModelNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/predict")
def classify_text(
    request: TextRequest,
    _operator: User = Depends(require_ml_operator),
):
    try:
        return news_analysis_pipeline.analyze_news(
            text=request.text,
            include_summary=False,
            allow_partial=True,
        )
    except ModelNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
