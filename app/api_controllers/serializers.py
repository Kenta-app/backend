from __future__ import annotations

from app.processed.models import MlPrediction, Summary
from app.raw.models import RawNews, Source
from app.serving.models import NewsClick, NewsReaction, NewsView, PublishedNews, User


def serialize_source(source: Source) -> dict:
    return {
        "sourceId": source.source_id,
        "name": source.name,
        "baseUrl": source.base_url,
        "type": source.type,
        "isActive": source.is_active,
        "createdAt": source.created_at.isoformat() if source.created_at else None,
    }


def serialize_user(user: User) -> dict:
    return {
        "userId": user.user_id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "createdAt": user.created_at.isoformat() if user.created_at else None,
    }


def serialize_published_news(news: PublishedNews) -> dict:
    return {
        "newsId": news.news_id,
        "representativeNewsProcessedId": news.representative_news_processed_id,
        "sourceId": news.source_id,
        "title": news.title,
        "summary": news.summary,
        "originalUrl": news.original_url,
        "sentimentLabel": news.sentiment_label,
        "sentimentScore": float(news.sentiment_score),
        "fakeScore": float(news.fake_score),
        "highRisk": float(news.fake_score) >= 0.80,
        "publishedAt": news.published_at.isoformat() if news.published_at else None,
    }


def serialize_raw_news(raw_news: RawNews) -> dict:
    return {
        "newsRawId": raw_news.news_raw_id,
        "sourceId": raw_news.source_id,
        "logId": raw_news.log_id,
        "platform": raw_news.platform,
        "sourceAccount": raw_news.source_account,
        "originalUrl": raw_news.original_url,
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
