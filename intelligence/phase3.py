from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import pandas as pd
from django.utils import timezone

from .models import ActionableEvent
from .phase2 import detect_regime
from .utils import classify_event

logger = logging.getLogger(__name__)


# _classification_for_event removed — using utils.classify_event instead.


def _build_hourly_frame(lookback_days: int = 45) -> pd.DataFrame:
    cutoff = timezone.now() - timedelta(days=lookback_days)
    rows = list(
        ActionableEvent.objects.filter(start_time__gte=cutoff)
        .order_by("start_time")
        .values("start_time", "duration_minutes", "focus_score", "event_type", "metadata")
    )
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["start_time"] = pd.to_datetime(frame["start_time"], utc=True).dt.tz_convert(
        timezone.get_current_timezone()
    )
    frame["hour"] = frame["start_time"].dt.hour
    frame["dow"] = frame["start_time"].dt.weekday
    frame["classification"] = frame.apply(
        lambda row: classify_event(row["event_type"], row["metadata"] or {}),
        axis=1,
    )
    frame["productive_minutes"] = frame.apply(
        lambda row: int(row["duration_minutes"] or 0) if row["classification"] == "Productive" else 0,
        axis=1,
    )
    frame["waste_minutes"] = frame.apply(
        lambda row: int(row["duration_minutes"] or 0) if row["classification"] == "Waste" else 0,
        axis=1,
    )
    frame["focus_value"] = frame["focus_score"].astype(float)
    return frame


def _sequence_forecast_24h(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []

    now_local = timezone.localtime()
    recent_focus = frame.dropna(subset=["focus_value"]).tail(24)["focus_value"]
    recent_focus_mean = float(recent_focus.mean()) if len(recent_focus) else 6.0
    max_prod = float(max(frame["productive_minutes"].max(), 1))

    forecasts = []
    for step in range(1, 25):
        ts = now_local + timedelta(hours=step)
        hour = ts.hour
        hour_slice = frame[frame["hour"] == hour]

        hour_focus = hour_slice.dropna(subset=["focus_value"])["focus_value"]
        hour_focus_mean = float(hour_focus.mean()) if len(hour_focus) else recent_focus_mean
        hour_prod_mean = float(hour_slice["productive_minutes"].mean()) if len(hour_slice) else 0.0
        hour_waste_mean = float(hour_slice["waste_minutes"].mean()) if len(hour_slice) else 0.0

        waste_penalty = min(1.5, hour_waste_mean / 40.0)
        predicted_focus = max(0.0, min(10.0, 0.65 * hour_focus_mean + 0.35 * recent_focus_mean - waste_penalty))
        support = int(len(hour_slice))
        confidence = min(0.95, 0.40 + support / 30.0)

        forecasts.append(
            {
                "timestamp": ts.isoformat(),
                "hour": hour,
                "predicted_focus": round(predicted_focus, 2),
                "productive_potential": round(hour_prod_mean / max_prod, 3),
                "waste_risk": round(min(1.0, hour_waste_mean / 60.0), 3),
                "confidence": round(confidence, 2),
                "support": support,
            }
        )
    return forecasts


def _suggested_task(regime: str, focus_score: float, waste_risk: float) -> str:
    if waste_risk > 0.6:
        return "Block social apps + short deep-work sprint"
    if regime == "burnout":
        return "Low-cognitive review + 10-min break"
    if regime == "exam":
        return "High-intensity problem solving"
    if focus_score >= 7.5:
        return "Advanced algorithm / deep coding block"
    return "Structured study block"


def _optimize_schedule_blocks(forecasts: list[dict[str, Any]], regime: str) -> list[dict[str, Any]]:
    ranked = []
    for item in forecasts:
        hour = item["hour"]
        focus_gain = item["predicted_focus"] / 10.0
        consistency = item["productive_potential"]
        fatigue_cost = 0.0
        if hour >= 22 or hour <= 5:
            fatigue_cost += 0.30
        elif hour >= 19:
            fatigue_cost += 0.15
        if regime == "burnout":
            fatigue_cost += 0.10
        if item["waste_risk"] > 0.5:
            fatigue_cost += 0.10

        score = focus_gain + consistency - fatigue_cost
        ranked.append(
            {
                "start_time": item["timestamp"],
                "end_time": (pd.to_datetime(item["timestamp"]) + pd.Timedelta(hours=1)).isoformat(),
                "hour": hour,
                "tradeoff_score": round(score, 3),
                "confidence": item["confidence"],
                "tradeoff": {
                    "focus_gain": round(focus_gain, 3),
                    "consistency": round(consistency, 3),
                    "fatigue_cost": round(fatigue_cost, 3),
                    "waste_risk": item["waste_risk"],
                },
                "suggested_task": _suggested_task(regime, item["predicted_focus"], item["waste_risk"]),
            }
        )

    ranked.sort(key=lambda row: row["tradeoff_score"], reverse=True)
    return ranked[:8]


def run_sequence_forecast_and_optimizer(lookback_days: int = 45) -> dict[str, Any]:
    frame = _build_hourly_frame(lookback_days=lookback_days)
    regime_payload = detect_regime(days=42)
    regime = regime_payload.get("regime_label", "normal")

    forecasts = _sequence_forecast_24h(frame)
    ranked = _optimize_schedule_blocks(forecasts, regime)
    return {
        "model_type": "sequence_heuristic_v1",
        "regime": regime,
        "forecast_count": len(forecasts),
        "ranked_blocks": ranked,
    }
