from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.ml.pipeline import ModelNotReadyError, news_analysis_pipeline

router = APIRouter()


class NewsAnalysisRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=500)
    content: Optional[str] = None
    text: Optional[str] = None
    include_summary: bool = True
    force_summary: bool = False

    @model_validator(mode="after")
    def validate_payload(self):
        if not any([self.title, self.content, self.text]):
            raise ValueError("Debes enviar title, content o text para analizar.")
        return self


class TextRequest(BaseModel):
    text: str


@router.get("/health")
def ml_health():
    return news_analysis_pipeline.get_status()


@router.post("/analyze")
def analyze_news(request: NewsAnalysisRequest):
    try:
        return news_analysis_pipeline.analyze_news(
            title=request.title,
            content=request.content,
            text=request.text,
            include_summary=request.include_summary,
            force_summary=request.force_summary,
        )
    except ModelNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/predict")
def classify_text(request: TextRequest):
    try:
        return news_analysis_pipeline.analyze_news(
            text=request.text,
            include_summary=False,
        )
    except ModelNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
