from __future__ import annotations

from app.processed.models import MlPrediction, Summary
from app.processed.text_utils import finish_truncated, repair_english_intrusions
from app.raw.models import RawNews, Source
from app.serving.models import (
    NewsClick,
    NewsDetailClick,
    NewsFavorite,
    NewsReaction,
    NewsView,
    PublishedNews,
    User,
    UserAppSession,
)


def serialize_source(source: Source) -> dict:
    return {
        "sourceId": source.source_id,
        "name": source.name,
        "baseUrl": source.base_url,
        "sourceAccount": source.source_account,
        "type": source.type,
        "isActive": source.is_active,
        "createdAt": source.created_at.isoformat() if source.created_at else None,
    }


def serialize_user(user: User) -> dict:
    return {
        "userId": user.user_id,
        "username": user.username,
        "email": user.email,
        "birthDate": user.birth_date.isoformat() if user.birth_date else None,
        "gender": user.gender,
        "role": (user.role or "user").lower(),
        "createdAt": user.created_at.isoformat() if user.created_at else None,
    }


def serialize_published_news(
    news: PublishedNews,
    *,
    source_name: str | None = None,
    prediction_id: int | None = None,
) -> dict:
    return {
        "newsId": news.news_id,
        "representativeNewsProcessedId": news.representative_news_processed_id,
        "predictionId": prediction_id,
        "sourceId": news.source_id,
        "sourceName": source_name or (news.source.name if news.source else None),
        "title": news.title,
        "summary": finish_truncated(repair_english_intrusions(news.summary)),
        "originalUrl": news.original_url,
        "imageUrl": news.image_url,
        "sentimentLabel": news.sentiment_label,
        "sentimentScore": float(news.sentiment_score),
        "fakeScore": float(news.fake_score),
        "highRisk": float(news.fake_score) >= 0.80,
        "publishedAt": news.published_at.isoformat() if news.published_at else None,
    }
    if sources is not None:
        payload["sources"] = sources
    return payload


def serialize_raw_news(raw_news: RawNews) -> dict:
    return {
        "newsRawId": raw_news.news_raw_id,
        "sourceId": raw_news.source_id,
        "logId": raw_news.log_id,
        "platform": raw_news.platform,
        "sourceAccount": raw_news.source_account,
        "originalUrl": raw_news.original_url,
        "imageUrl": raw_news.image_url,
        "titleRaw": raw_news.title_raw,
        "authorRaw": raw_news.author_raw,
        "publishedAt": raw_news.published_at.isoformat() if raw_news.published_at else None,
        "scrapedAt": raw_news.scraped_at.isoformat() if raw_news.scraped_at else None,
        "status": raw_news.status,
    }


def serialize_prediction(prediction: MlPrediction) -> dict:
    return {
        "predictionId": prediction.prediction_id,
        "representativeNewsProcessedId": prediction.representative_news_processed_id,
        "sentimentLabel": prediction.sentiment_label,
        "sentimentScore": float(prediction.sentiment_score),
        "modelVersion": prediction.model_version,
        "createdAt": prediction.created_at.isoformat() if prediction.created_at else None,
        "fakeScore": float(prediction.fake_score),
        "highRisk": float(prediction.fake_score) >= 0.80,
    }


def serialize_summary(summary: Summary) -> dict:
    return {
        "summaryId": summary.summary_id,
        "representativeNewsProcessedId": summary.representative_news_processed_id,
        "summaryText": summary.summary_text,
        "modelVersion": summary.model_version,
        "createdAt": summary.created_at.isoformat() if summary.created_at else None,
    }


def serialize_reaction(item: NewsReaction) -> dict:
    return {
        "reactionId": item.reaction_id,
        "userId": item.user_id,
        "newsId": item.news_id,
        "reaction": item.reaction,
        "createdAt": item.created_at.isoformat() if item.created_at else None,
    }


def serialize_view(item: NewsView) -> dict:
    return {
        "viewId": item.view_id,
        "userId": item.user_id,
        "newsId": item.news_id,
        "viewedAt": item.viewed_at.isoformat() if item.viewed_at else None,
        "timeSpentSec": item.time_spent_sec,
    }


def serialize_click(item: NewsClick) -> dict:
    return {
        "clickId": item.click_id,
        "userId": item.user_id,
        "newsId": item.news_id,
        "clickedAt": item.clicked_at.isoformat() if item.clicked_at else None,
    }


def serialize_detail_click(item: NewsDetailClick) -> dict:
    return {
        "detailClickId": item.detail_click_id,
        "userId": item.user_id,
        "newsId": item.news_id,
        "clickedAt": item.clicked_at.isoformat() if item.clicked_at else None,
    }


def serialize_session(item: UserAppSession) -> dict:
    return {
        "sessionId": item.session_id,
        "userId": item.user_id,
        "timeSpentSec": item.time_spent_sec,
        "startedAt": item.started_at.isoformat() if item.started_at else None,
        "endedAt": item.ended_at.isoformat() if item.ended_at else None,
    }


def serialize_favorite(
    favorite: NewsFavorite,
    news: PublishedNews | None = None,
    source_name: str | None = None,
) -> dict:
    payload = {
        "favoriteId": favorite.favorite_id,
        "userId": favorite.user_id,
        "newsId": favorite.news_id,
        "savedAt": favorite.saved_at.isoformat() if favorite.saved_at else None,
        "isFavorite": True,
    }
    if news is not None:
        payload["news"] = serialize_published_news(news, source_name=source_name)
    return payload
