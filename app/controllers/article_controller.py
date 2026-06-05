from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db.database import get_db
from app.schemas.articlebase import ArticleResponse
from app.services.article_service import ArticleService

router = APIRouter()

@router.get("", response_model=List[ArticleResponse])
def get_articles(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return ArticleService.get_all(db, skip=skip, limit=limit)

@router.get("/{article_id}", response_model=ArticleResponse)
def get_article_by_id(article_id: int, db: Session = Depends(get_db)):
    article = ArticleService.get_by_id(db, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article