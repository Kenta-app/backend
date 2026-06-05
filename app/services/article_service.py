from sqlalchemy.orm import Session
from app.models.article import Article
from typing import List, Optional

class ArticleService:
    @staticmethod
    def get_by_id(db: Session, news_id: int) -> Optional[Article]:
        return db.query(Article).filter(Article.id == news_id).first()

    @staticmethod
    def get_all(db: Session, skip: int = 0, limit: int = 100) -> List[Article]:
        return db.query(Article).offset(skip).limit(limit).all()
