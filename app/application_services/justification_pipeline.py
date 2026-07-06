from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

from app.dependencies import is_justification_auto_enabled

if TYPE_CHECKING:
    from app.interfaces.justification_service import IJustificationService

logger = logging.getLogger(__name__)


def auto_justify_prediction(
    justification_service: Optional["IJustificationService"],
    prediction_id: int,
) -> None:
    if justification_service is None or not is_justification_auto_enabled():
        return
    if not os.getenv("GEMINI_API_KEY"):
        return

    justification_service.generate_justification_safe(
        prediction_id=prediction_id,
        include_context=True,
        regenerate=False,
    )
