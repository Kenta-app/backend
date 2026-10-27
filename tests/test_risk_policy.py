from app.api_controllers.serializers import serialize_published_news
from app.application_services.preprocessing_service import PreprocessingService
from app.ml.risk_policy import FakeNewsRiskPolicy
from app.raw.models import RawNews, Source
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


def test_official_source_withholds_unvalidated_public_score_instead_of_forcing_truth():
    source = Source(
        name="El Peruano",
        base_url="https://elperuano.pe/",
        type="web",
    )
    news = PublishedNews(
        representative_news_processed_id=2,
        source_id=1,
        source=source,
        title="Comunicado oficial",
        original_url="https://elperuano.pe/noticia/ejemplo",
        fake_score=0.93,
    )

    payload = serialize_published_news(news)

    assert payload["fakeScore"] is None
    assert payload["riskLevel"] == "not_assessed"
    assert payload["analysisStatus"] == "withheld_source_policy"
    assert payload["highRisk"] is False
    assert payload["sourceAuthority"]["authority_type"] == "official_state_publisher"
    assert "no la veracidad automática" in payload["sourceAuthority"]["reason"]


def test_social_preprocessing_includes_quoted_post_as_labeled_context():
    raw = RawNews(
        platform="twitter",
        content_raw="Esto confirma la noticia",
        social_context={
            "references": [
                {
                    "type": "quoted",
                    "status": "available",
                    "account": "medio",
                    "text": "El Congreso aprobó la medida anunciada.",
                }
            ]
        },
    )

    text = PreprocessingService(None)._build_raw_text(raw)

    assert "Publicación analizada: Esto confirma la noticia" in text
    assert "Publicación citada de medio: El Congreso aprobó" in text
