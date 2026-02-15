from fastapi import APIRouter
from pydantic import BaseModel
from app.ml.roberta_loader import predict

router = APIRouter()

class TextRequest(BaseModel):
    text: str

@router.post("/predict")
def classify_text(request: TextRequest):
    return predict(request.text)
