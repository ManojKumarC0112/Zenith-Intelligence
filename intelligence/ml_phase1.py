from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pandas as pd
from django.utils import timezone

from .models import ActionableEvent


PRODUCTIVE_KEYWORDS = ("deep work", "study", "algorithm")
WASTE_LABEL = "waste"


def _is_productive(event_type: str, metadata: dict[str, Any]) -> bool:
    lowered = (event_type or "").lower()
    if any(token in lowered for token in PRODUCTIVE_KEYWORDS):
        return True
    classification = (metadata or {}).get("classification", "")
    return str(classification).lower() == "productive"


def _is_waste(event_type: str, metadata: dict[str, Any]) -> bool:
    lowered = (event_type or "").lower()
    if WASTE_LABEL in lowered:
        return True
    classification = (metadata or {}).get("classification", "")
    return str(classification).lower() == WASTE_LABEL


def build_feature_frame(lookback_days: int = 60) -> pd.DataFrame:
    cutoff = timezone.now() - timedelta(days=lookback_days)
    rows = (
        ActionableEvent.objects.filter(start_time__gte=cutoff)
        .order_by("start_time")
        .values("start_time", "event_type", "duration_minutes", "focus_score", "metadata")
    )
    if not rows:
        return pd.DataFrame()

    frame = pd.DataFrame(rows)
    frame["start_time"] = pd.to_datetime(frame["start_time"], utc=True).dt.tz_convert(
        timezone.get_current_timezone()
    )
    frame["hour"] = frame["start_time"].dt.hour
    frame["weekday"] = frame["start_time"].dt.weekday
    frame["is_productive"] = frame.apply(
        lambda row: _is_productive(row["event_type"], row["metadata"] or {}),
        axis=1,
    )
    frame["is_waste"] = frame.apply(
        lambda row: _is_waste(row["event_type"], row["metadata"] or {}),
        axis=1,
    )

    # Event-to-event context features.
    frame["prev_start_time"] = frame["start_time"].shift(1)
    frame["prev_event_type"] = frame["event_type"].shift(1)
    frame["break_minutes"] = (
        (frame["start_time"] - frame["prev_start_time"]).dt.total_seconds().fillna(0) / 60.0
    )
    frame["app_switch"] = (frame["event_type"] != frame["prev_event_type"]).astype(int)
    frame.loc[0, "app_switch"] = 0
    return frame


@dataclass
class Phase1Output:
    feature_store: dict[str, Any]
    probabilistic_forecast: list[dict[str, Any]]
    anomaly_detection: dict[str, Any]


def probabilistic_forecast(frame: pd.DataFrame, horizon_hours: int = 24) -> list[dict[str, Any]]:
    if frame.empty:
        return []

    focus_frame = frame.dropna(subset=["focus_score"]).copy()
    if focus_frame.empty:
        return []

    overall_p10 = float(focus_frame["focus_score"].quantile(0.10))
    overall_p50 = float(focus_frame["focus_score"].quantile(0.50))
    overall_p90 = float(focus_frame["focus_score"].quantile(0.90))

    now_local = timezone.localtime()
    by_hour = {
        hour: group["focus_score"].astype(float).tolist()
        for hour, group in focus_frame.groupby("hour")
    }

    result = []
    for step in range(1, horizon_hours + 1):
        point = now_local + timedelta(hours=step)
        samples = by_hour.get(point.hour, [])
        if len(samples) >= 5:
            series = pd.Series(samples)
            p10 = float(series.quantile(0.10))
            p50 = float(series.quantile(0.50))
            p90 = float(series.quantile(0.90))
            support = len(samples)
        else:
            p10, p50, p90 = overall_p10, overall_p50, overall_p90
            support = len(samples)
        confidence = min(0.95, 0.45 + (support / 20.0))
        result.append(
            {
                "timestamp": point.isoformat(),
                "hour": point.hour,
                "p10": round(p10, 2),
                "p50": round(p50, 2),
                "p90": round(p90, 2),
                "confidence": round(confidence, 2),
            }
        )
    return result


def anomaly_summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"status": "insufficient_data"}

    day_frame = frame.copy()
    day_frame["day"] = day_frame["start_time"].dt.date
    day_agg = (
        day_frame.groupby("day")
        .agg(
            productive_minutes=("duration_minutes", lambda s: int(day_frame.loc[s.index, "is_productive"].mul(s).sum())),
            waste_minutes=("duration_minutes", lambda s: int(day_frame.loc[s.index, "is_waste"].mul(s).sum())),
        )
        .sort_index()
    )
    if len(day_agg) < 8:
        return {"status": "insufficient_data"}

    recent = day_agg.tail(7)
    baseline = day_agg.iloc[:-7].tail(21)
    if baseline.empty:
        return {"status": "insufficient_data"}

    recent_prod_mean = float(recent["productive_minutes"].mean())
    baseline_prod_mean = float(baseline["productive_minutes"].mean())
    baseline_prod_std = float(baseline["productive_minutes"].std(ddof=0))
    z_score = (
        (recent_prod_mean - baseline_prod_mean) / baseline_prod_std
        if baseline_prod_std > 0
        else 0.0
    )

    recent_waste_mean = float(recent["waste_minutes"].mean())
    baseline_waste_mean = float(baseline["waste_minutes"].mean())
    waste_delta_pct = (
        ((recent_waste_mean - baseline_waste_mean) / baseline_waste_mean) * 100.0
        if baseline_waste_mean > 0
        else 0.0
    )

    level = "normal"
    if z_score <= -1.5 or waste_delta_pct >= 35:
        level = "high"
    elif z_score <= -0.75 or waste_delta_pct >= 20:
        level = "medium"

    return {
        "status": "ok",
        "risk_level": level,
        "productive_z_score": round(z_score, 2),
        "waste_delta_pct": round(waste_delta_pct, 2),
        "recent_avg_productive_minutes": round(recent_prod_mean, 1),
        "baseline_avg_productive_minutes": round(baseline_prod_mean, 1),
    }


def build_phase1_output(lookback_days: int = 60) -> Phase1Output:
    frame = build_feature_frame(lookback_days=lookback_days)
    columns = [
        "start_time",
        "event_type",
        "duration_minutes",
        "focus_score",
        "hour",
        "weekday",
        "is_productive",
        "is_waste",
        "break_minutes",
        "app_switch",
    ]
    present_columns = [col for col in columns if col in frame.columns]
    feature_store = {
        "lookback_days": lookback_days,
        "row_count": int(len(frame)),
        "columns": present_columns,
    }
    return Phase1Output(
        feature_store=feature_store,
        probabilistic_forecast=probabilistic_forecast(frame),
        anomaly_detection=anomaly_summary(frame),
    )
