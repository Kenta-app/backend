from __future__ import annotations

from datetime import datetime
from typing import List
import unicodedata

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload

from app.interfaces.news_repository import INewsRepository
from app.raw.models import Source
from app.serving.models import PublishedNews


class NewsRepository(INewsRepository):
    def __init__(self, db: Session):
        self.db = db

    def findById(self, newsId: int) -> PublishedNews | None:
        return (
            self.db.query(PublishedNews)
            .options(joinedload(PublishedNews.source))
            .filter(PublishedNews.news_id == newsId)
            .first()
        )

    def findAll(self, page: int, pageSize: int) -> List[PublishedNews]:
        offset = max(page - 1, 0) * pageSize
        return (
            self.db.query(PublishedNews)
            .options(joinedload(PublishedNews.source))
            .order_by(PublishedNews.published_at.desc(), PublishedNews.news_id.desc())
            .offset(offset)
            .limit(pageSize)
            .all()
        )

    def countPublished(self) -> int:
        return (
            self.db.query(PublishedNews)
            .filter(PublishedNews.published_at.isnot(None))
            .count()
        )

    def findFeed(
        self,
        *,
        page: int,
        pageSize: int,
        sourceId: int | None = None,
        sourceName: str | None = None,
        title: str | None = None,
        since: datetime | None = None,
        before: tuple[datetime, int] | None = None,
    ) -> tuple[List[PublishedNews], int]:
        query = self.db.query(PublishedNews).filter(PublishedNews.published_at.isnot(None))
        if sourceId is not None:
            query = query.filter(PublishedNews.source_id == sourceId)
        elif sourceName:
            query = query.join(Source).filter(Source.name == sourceName)
        if title:
            normalized_title = "".join(
                char for char in unicodedata.normalize("NFKD", title.casefold())
                if not unicodedata.combining(char)
            )
            escaped = normalized_title.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            folded_column = PublishedNews.title
            for accented, plain in (
                ("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
                ("ü", "u"), ("ñ", "n"), ("Á", "a"), ("É", "e"), ("Í", "i"),
                ("Ó", "o"), ("Ú", "u"), ("Ü", "u"), ("Ñ", "n"),
            ):
                folded_column = func.replace(folded_column, accented, plain)
            query = query.filter(func.lower(folded_column).like(f"%{escaped}%", escape="\\"))
        if since is not None:
            query = query.filter(PublishedNews.published_at >= since)

        total = query.count()
        query = query.options(joinedload(PublishedNews.source)).order_by(
            PublishedNews.published_at.desc(), PublishedNews.news_id.desc()
        )
        if before is not None:
            published_at, news_id = before
            query = query.filter(
                or_(
                    PublishedNews.published_at < published_at,
                    and_(PublishedNews.published_at == published_at, PublishedNews.news_id < news_id),
                )
            )
        elif page > 1:
            query = query.offset((page - 1) * pageSize)
        items = query.limit(pageSize + 1).all()
        return items, total

    def save(self, news: PublishedNews) -> PublishedNews:
        self.db.add(news)
        self.db.commit()
        self.db.refresh(news)
        return news

    def findBySourceId(self, sourceId: int) -> List[PublishedNews]:
        return (
            self.db.query(PublishedNews)
            .options(joinedload(PublishedNews.source))
            .filter(PublishedNews.source_id == sourceId)
            .order_by(PublishedNews.published_at.desc(), PublishedNews.news_id.desc())
            .all()
        )

    def findBySourceName(self, sourceName: str) -> List[PublishedNews]:
        return (
            self.db.query(PublishedNews)
            .join(Source, PublishedNews.source_id == Source.source_id)
            .options(joinedload(PublishedNews.source))
            .filter(Source.name == sourceName)
            .order_by(PublishedNews.published_at.desc(), PublishedNews.news_id.desc())
            .all()
        )
