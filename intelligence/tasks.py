"""
Celery tasks — scheduled ML pipeline stages.

Each stage is a @shared_task so Celery Beat can run them on a schedule.
The Prophet daily-schedule task is also called by ScheduleView, which
now serves a cached result rather than training synchronously.

Fixes vs original:
 - Prophet trained on last 90 days only (prevents unbounded growth).
 - print() replaced with logging.
 - Schedule result cached to DB via ScheduleCache model (served async).
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pandas as pd
from celery import shared_task
from django.core.cache import cache
from django.utils import timezone
from prophet import Prophet

from .ml_phase1 import build_phase1_output
from .models import ActionableEvent
from .phase2 import detect_regime, run_representation_pipeline
from .phase3 import run_sequence_forecast_and_optimizer
from .phase4 import estimate_uplift, recommend_actions
from .phase5 import graph_summary_and_leverage, rebuild_influence_graph

logger = logging.getLogger(__name__)

# Cache key used by ScheduleView to serve the last trained schedule.
SCHEDULE_CACHE_KEY = "focusos:daily_schedule"
SCHEDULE_CACHE_TTL = 60 * 60 * 26  # 26 hours


@shared_task
def generate_daily_schedule():
    """
    Train a Prophet model on the last 90 days of focus data and predict
    peak focus windows for tomorrow.  Result is stored in Django's cache
    layer so ScheduleView can return it instantly without blocking.
    """
    logger.info("generate_daily_schedule: starting Prophet training…")

    # ── 90-day lookback (fixes unbounded growth) ──────────────────────────
    cutoff = timezone.now() - timedelta(days=90)
    events = ActionableEvent.objects.filter(
        start_time__gte=cutoff
    ).exclude(focus_score__isnull=True).values("start_time", "focus_score")

    if len(events) < 10:
        result = {"status": "Waiting for more data. Need at least 10 logged sessions with focus scores."}
        cache.set(SCHEDULE_CACHE_KEY, result, SCHEDULE_CACHE_TTL)
        return result

    df = pd.DataFrame(events)
    df["ds"] = pd.to_datetime(df["start_time"]).dt.tz_localize(None)
    df["y"] = df["focus_score"]

    model = Prophet(daily_seasonality=True, yearly_seasonality=False, weekly_seasonality=True)
    model.fit(df)

    future_dates = model.make_future_dataframe(periods=24, freq="h")
    forecast = model.predict(future_dates)

    tomorrow = (timezone.localtime() + timedelta(days=1)).date()
    tomorrow_forecast = forecast[forecast["ds"].dt.date == tomorrow]
    peak_hours = tomorrow_forecast.nlargest(2, "yhat")

    recommendations = []
    for _, row in peak_hours.iterrows():
        hour_string = row["ds"].strftime("%I:00 %p")
        predicted_score = round(row["yhat"], 1)
        recommendations.append(
            {
                "time": hour_string,
                "predicted_focus": predicted_score,
                "suggested_task": "Advanced Algorithm Practice / Deep Work",
            }
        )

    result = {"status": "ok", "schedule": recommendations}
    cache.set(SCHEDULE_CACHE_KEY, result, SCHEDULE_CACHE_TTL)
    logger.info("generate_daily_schedule: done — %d peak slots found.", len(recommendations))
    return result


@shared_task
def run_phase1_ml_pipeline():
    """Builds Phase 1 feature store stats, probabilistic forecast, and anomaly scores."""
    logger.info("run_phase1_ml_pipeline: starting…")
    output = build_phase1_output(lookback_days=60)
    logger.info("run_phase1_ml_pipeline: complete.")
    return {
        "feature_store": output.feature_store,
        "probabilistic_forecast": output.probabilistic_forecast,
        "anomaly_detection": output.anomaly_detection,
    }


@shared_task
def run_phase2_representation_pipeline():
    logger.info("run_phase2_representation_pipeline: starting…")
    embedding_result = run_representation_pipeline(days=45)
    regime_result = detect_regime(days=42)
    logger.info("run_phase2_representation_pipeline: complete.")
    return {"embedding": embedding_result, "regime": regime_result}


@shared_task
def run_phase3_sequence_optimizer():
    logger.info("run_phase3_sequence_optimizer: starting…")
    result = run_sequence_forecast_and_optimizer(lookback_days=45)
    logger.info("run_phase3_sequence_optimizer: complete.")
    return result


@shared_task
def run_phase4_decisioning_pipeline():
    logger.info("run_phase4_decisioning_pipeline: starting…")
    result = {
        "recommendations": recommend_actions(top_k=2),
        "uplift": estimate_uplift(),
    }
    logger.info("run_phase4_decisioning_pipeline: complete.")
    return result


@shared_task
def run_phase5_graph_pipeline():
    logger.info("run_phase5_graph_pipeline: starting…")
    build = rebuild_influence_graph(lookback_days=60)
    summary = graph_summary_and_leverage(top_k=8)
    logger.info("run_phase5_graph_pipeline: complete. edges=%s", build.get("edge_count"))
    return {"build": build, "summary": summary}
