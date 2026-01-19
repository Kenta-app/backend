from pydantic import BaseModel, HttpUrl
from datetime import datetime
from typing import Optional

class ArticleBase(BaseModel):
    title: str
    url: str
    content: Optional[str] = None
    summary: Optional[str] = None
    author: Optional[str] = None
    source: str
    published_date: Optional[datetime] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    image_url: Optional[str] = None

class ArticleCreate(ArticleBase):
    pass

class ArticleResponse(ArticleBase):
    id: int
    scraped_date: datetime
    is_active: bool

    class Config:
        from_attributes = True

class ScrapingLogResponse(BaseModel):
    id: int
    source: str
    status: str
    articles_scraped: int
    error_message: Optional[str]
    started_at: datetime
    finished_at: Optional[datetime]

    class Config:
        from_attributes = True