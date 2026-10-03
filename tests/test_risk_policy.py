from app.api_controllers.serializers import serialize_published_news
from app.application_services.preprocessing_service import PreprocessingService
from app.ml.risk_policy import FakeNewsRiskPolicy
from app.raw.models import RawNews
from app.serving.models import PublishedNews


def test_risk_policy_uses_one_consistent_three_way_boundary():
    policy = FakeNewsRiskPolicy(low_threshold=0.35, high_threshold=0.75)

    assert policy.classify(0.35) == "likely_real"
    assert policy.classify(0.36) == "indeterminate"
    assert policy.classify(0.74) == "indeterminate"
    assert policy.classify(0.75) == "likely_fake"


def test_news_serializer_exposes_policy_instead_of_a_second_threshold(monkeypatch):
    monkeypatch.setenv("FAKENEWS_ARTICLE_LOW_THRESHOLD", "0.30")
    monkeypatch.setenv("FAKENEWS_ARTICLE_HIGH_THRESHOLD", "0.80")
    news = PublishedNews(
        representative_news_processed_id=1,
        source_id=1,
        title="Noticia",
        original_url="https://example.com/noticia",
        fake_score=0.79,
    )

    payload = serialize_published_news(news)

    assert payload["riskLevel"] == "indeterminate"
    assert payload["highRisk"] is False
    assert payload["riskThresholds"] == {"low": 0.3, "high": 0.8}


def test_social_posts_use_a_shorter_minimum_than_articles():
    social = RawNews(platform="twitter")
    article = RawNews(platform="web")

    assert PreprocessingService.minimumTokens(social) == 8
    assert PreprocessingService.minimumTokens(article) == 50
