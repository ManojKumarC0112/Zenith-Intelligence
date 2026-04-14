"""
Shared utility functions for the intelligence app.
Centralised here to avoid copy-paste across phase modules.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Activity classification helpers
# ---------------------------------------------------------------------------

_PRODUCTIVE_TOKENS = ("deep work", "study", "algorithm", "leetcode", "neetcode")
_WASTE_TOKEN = "waste"


def classify_event(event_type: str, metadata: dict) -> str:
    """
    Return 'Productive', 'Waste', or 'Neutral' for a tracked event.

    Priority order:
    1. Explicit 'classification' key in metadata (set by observer daemon).
    2. Keyword match on event_type string.
    3. Default to 'Neutral'.
    """
    cls = str((metadata or {}).get("classification", "")).strip().lower()
    if cls == "productive":
        return "Productive"
    if cls == "waste":
        return "Waste"
    if cls == "neutral":
        return "Neutral"

    lowered = (event_type or "").lower()
    if any(token in lowered for token in _PRODUCTIVE_TOKENS):
        return "Productive"
    if _WASTE_TOKEN in lowered:
        return "Waste"

    return "Neutral"
