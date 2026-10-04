import pytest

from app.tasks.scheduler import (
    configured_justification_budget,
    configured_scraping_times,
    select_balanced_prediction_ids,
)


def test_schedule_accepts_two_separated_hours(monkeypatch):
    monkeypatch.setenv("SCRAPING_SCHEDULE_HOURS", "20,8")
    monkeypatch.setenv("SCRAPING_SCHEDULE_MINUTE", "30")

    assert configured_scraping_times() == ([8, 20], 30)


def test_schedule_preserves_legacy_single_hour(monkeypatch):
    monkeypatch.delenv("SCRAPING_SCHEDULE_HOURS", raising=False)
    monkeypatch.setenv("SCRAPING_SCHEDULE_HOUR", "20")
    monkeypatch.setenv("SCRAPING_SCHEDULE_MINUTE", "30")

    assert configured_scraping_times() == ([20], 30)


@pytest.mark.parametrize("hours", ["", "8,24", "8,noon", "8,,20", "0,1,2,3,4,5,6"])
def test_schedule_rejects_invalid_or_excessive_hours(monkeypatch, hours):
    monkeypatch.setenv("SCRAPING_SCHEDULE_HOURS", hours)
    monkeypatch.setenv("SCRAPING_SCHEDULE_HOUR", "25")

    with pytest.raises(ValueError):
        configured_scraping_times()


def test_automatic_related_source_budget_is_bounded(monkeypatch):
    monkeypatch.setenv("JUSTIFICATION_MAX_PER_SCHEDULED_RUN", "5")
    assert configured_justification_budget() == 5

    monkeypatch.setenv("JUSTIFICATION_MAX_PER_SCHEDULED_RUN", "51")
    with pytest.raises(ValueError):
        configured_justification_budget()


def test_related_source_budget_is_balanced_and_rotatable():
    predictions = {
        1: [101, 102, 103],
        2: [201, 202],
        3: [301],
    }

    assert select_balanced_prediction_ids(predictions, limit=5) == [
        101,
        201,
        301,
        102,
        202,
    ]
    assert select_balanced_prediction_ids(predictions, limit=2, rotation=1) == [
        201,
        301,
    ]
