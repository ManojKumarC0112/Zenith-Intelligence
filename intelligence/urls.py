from django.urls import path

from .views import (
    AnalyticsView,
    ClassificationQualityView,
    DecisionRecommendationView,
    DecisionUpliftView,
    HealthCheckView,
    InfluenceGraphView,
    IngestEventView,
    InterventionLogView,
    PrivacyStatusView,
    RankedScheduleView,
    RegimeView,
    ScheduleView,
)

urlpatterns = [
    # ── Data ingestion ────────────────────────────────────────────────────────
    path("ingest/", IngestEventView.as_view(), name="ingest-event"),

    # ── Analytics ─────────────────────────────────────────────────────────────
    path("api/analytics/", AnalyticsView.as_view(), name="analytics"),
    path("api/analytics/regime/", RegimeView.as_view(), name="regime"),
    path("api/analytics/classification-quality/", ClassificationQualityView.as_view(), name="classification-quality"),

    # ── Schedule / optimiser ──────────────────────────────────────────────────
    path("api/schedule/", ScheduleView.as_view(), name="schedule"),
    path("api/schedule/ranked/", RankedScheduleView.as_view(), name="ranked-schedule"),

    # ── Decision engine ───────────────────────────────────────────────────────
    path("api/decision/recommend/", DecisionRecommendationView.as_view(), name="decision-recommend"),
    path("api/decision/uplift/", DecisionUpliftView.as_view(), name="decision-uplift"),
    path("api/decision/log/", InterventionLogView.as_view(), name="decision-log"),

    # ── Influence graph ───────────────────────────────────────────────────────
    path("api/graph/influence/", InfluenceGraphView.as_view(), name="graph-influence"),

    # ── Privacy & system ──────────────────────────────────────────────────────
    path("api/privacy/status/", PrivacyStatusView.as_view(), name="privacy-status"),
    path("api/health/", HealthCheckView.as_view(), name="health-check"),
]
