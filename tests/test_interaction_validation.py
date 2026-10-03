from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.api_controllers.interaction_controller import (
    InteractionBatchRequest,
    ReactionRequest,
)


def test_reaction_rejects_values_outside_the_supported_pair():
    with pytest.raises(ValidationError):
        ReactionRequest(newsId=1, reaction=0)


def test_tracking_rejects_unbounded_duration_and_stale_sessions():
    with pytest.raises(ValidationError):
        InteractionBatchRequest(
            events=[{"type": "view", "newsId": 1, "timeSpentSec": 86_401}]
        )

    with pytest.raises(ValidationError):
        InteractionBatchRequest(
            events=[
                {
                    "type": "session",
                    "timeSpentSec": 10,
                    "startedAt": datetime.utcnow() - timedelta(days=3),
                }
            ]
        )


def test_related_click_accepts_only_http_urls():
    with pytest.raises(ValidationError):
        InteractionBatchRequest(
            events=[
                {
                    "type": "related-click",
                    "newsId": 1,
                    "targetUrl": "javascript:alert(1)",
                }
            ]
        )

    payload = InteractionBatchRequest(
        events=[
            {
                "type": "related-click",
                "newsId": 1,
                "targetUrl": "https://example.com/evidence",
                "sourceName": "  Fuente   verificadora  ",
            }
        ]
    )
    assert payload.events[0].sourceName == "Fuente verificadora"
