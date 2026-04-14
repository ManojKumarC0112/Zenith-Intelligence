"""
Phase 4 — Contextual Decisioning & Causal Uplift Estimation

Uses a UCB1-style bandit to recommend the next best action, and
estimates the per-action uplift relative to baseline reward from the
InterventionLog table.

Fixes vs original:
 - ACTION_SPACE is derived dynamically from logged interventions
   so new actions are auto-discovered.
 - UCB1 bonus uses the correct formula: sqrt(2 * log(N) / n).
 - Classification helper imported from shared utils.py.
"""

from __future__ import annotations

import logging
import math
from datetime import timedelta
from typing import Any

import numpy as np
from django.db.models import Avg
from django.utils import timezone

from .models import ActionableEvent, InterventionLog
from .phase2 import detect_regime
from .utils import classify_event

logger = logging.getLogger(__name__)

# Default actions present even before any InterventionLog records exist.
_DEFAULT_ACTION_SPACE = [
    "start_deep_work",
    "short_break",
    "block_social_app",
]


def _get_action_space() -> list[str]:
    """Return all known actions — defaults union logged actions."""
    from_db = list(
        InterventionLog.objects.values_list("action", flat=True).distinct()
    )
    known = set(_DEFAULT_ACTION_SPACE) | set(from_db)
    return sorted(known)


def build_current_context(window_hours: int = 3) -> dict[str, Any]:
    now = timezone.localtime()
    cutoff = now - timedelta(hours=window_hours)
    rows = list(
        ActionableEvent.objects.filter(start_time__gte=cutoff).values(
            "event_type", "duration_minutes", "focus_score", "metadata"
        )
    )
    productive = waste = neutral = 0
    for row in rows:
        label = classify_event(row["event_type"], row["metadata"] or {})
        minutes = int(row["duration_minutes"] or 0)
        if label == "Productive":
            productive += minutes
        elif label == "Waste":
            waste += minutes
        else:
            neutral += minutes

    focus = (
        ActionableEvent.objects.filter(start_time__gte=cutoff, focus_score__isnull=False)
        .aggregate(avg=Avg("focus_score"))
        .get("avg")
    )
    regime = detect_regime(days=42).get("regime_label", "normal")
    return {
        "hour": now.hour,
        "productive_minutes_recent": productive,
        "waste_minutes_recent": waste,
        "neutral_minutes_recent": neutral,
        "avg_focus_recent": round(float(focus), 2) if focus is not None else None,
        "regime": regime,
    }


def _action_prior(action: str, context: dict[str, Any]) -> float:
    hour = int(context.get("hour", 12))
    waste_recent = float(context.get("waste_minutes_recent", 0))
    productive_recent = float(context.get("productive_minutes_recent", 0))
    regime = str(context.get("regime", "normal"))

    if action == "block_social_app":
        return 0.6 if waste_recent >= 20 else 0.2
    if action == "short_break":
        return 0.55 if regime == "burnout" or productive_recent >= 90 else 0.25
    if action == "start_deep_work":
        base = 0.5 if 8 <= hour <= 13 else 0.35
        if regime == "exam":
            base += 0.10
        if waste_recent > productive_recent:
            base -= 0.08
        return max(0.1, min(0.9, base))
    # Unknown / custom action — neutral prior
    return 0.25


def recommend_actions(top_k: int = 2) -> dict[str, Any]:
    context = build_current_context(window_hours=3)
    logs = list(InterventionLog.objects.all()[:500])
    total_logs = len(logs)
    action_space = _get_action_space()

    candidates = []
    for action in action_space:
        action_logs = [log for log in logs if log.action == action and log.reward is not None]
        n = len(action_logs)
        mean_reward = float(np.mean([float(log.reward) for log in action_logs])) if n else 0.0

        # Correct UCB1: sqrt(2 * ln(N+1) / (n+1))
        ucb_bonus = math.sqrt(2.0 * math.log(total_logs + 1) / (n + 1))
        prior = _action_prior(action, context)
        score = prior + mean_reward + 0.35 * ucb_bonus
        predicted_uplift = max(0.0, min(35.0, score * 12.0))
        candidates.append(
            {
                "action": action,
                "score": round(score, 4),
                "predicted_uplift_pct": round(predicted_uplift, 2),
                "sample_size": n,
                "why": f"prior={prior:.2f}, mean_reward={mean_reward:.2f}, exploration={ucb_bonus:.2f}",
            }
        )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    logger.debug("Recommended %d actions from space of %d", top_k, len(action_space))
    return {
        "context": context,
        "recommended_actions": candidates[:top_k],
    }


def estimate_uplift() -> dict[str, Any]:
    logs = list(InterventionLog.objects.filter(reward__isnull=False)[:1000])
    if len(logs) < 8:
        return {"status": "insufficient_data", "action_uplift": []}

    action_space = _get_action_space()
    overall = float(np.mean([float(log.reward) for log in logs]))
    action_uplift = []
    for action in action_space:
        treated = [float(log.reward) for log in logs if log.action == action]
        if not treated:
            action_uplift.append(
                {"action": action, "uplift_pct": 0.0, "confidence": 0.0, "treated_count": 0}
            )
            continue
        treated_mean = float(np.mean(treated))
        uplift = (treated_mean - overall) * 100.0
        confidence = min(0.92, 0.35 + len(treated) / 60.0)
        action_uplift.append(
            {
                "action": action,
                "uplift_pct": round(uplift, 2),
                "confidence": round(confidence, 2),
                "treated_count": len(treated),
            }
        )

    action_uplift.sort(key=lambda row: row["uplift_pct"], reverse=True)
    return {
        "status": "ok",
        "baseline_reward": round(overall, 4),
        "action_uplift": action_uplift,
    }
