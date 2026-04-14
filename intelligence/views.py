import logging
from collections import defaultdict
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Avg, Q, Sum
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .insights_service import generate_productivity_insights
from .ml_phase1 import build_phase1_output
from .models import ActionableEvent, InterventionLog
from .phase2 import classification_quality, detect_regime
from .phase3 import run_sequence_forecast_and_optimizer
from .phase4 import estimate_uplift, recommend_actions
from .phase5 import graph_summary_and_leverage, privacy_status, rebuild_influence_graph
from .serializers import ActionableEventSerializer
from .tasks import SCHEDULE_CACHE_KEY, generate_daily_schedule
from .utils import classify_event

logger = logging.getLogger(__name__)


# _classification_for_event removed — use utils.classify_event instead.


class IngestEventView(generics.CreateAPIView):
    queryset = ActionableEvent.objects.all()
    serializer_class = ActionableEventSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {
                "status": "success",
                "message": f"Logged {serializer.data['event_type']} successfully.",
                "data": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )


class ScheduleView(APIView):
    def get(self, request, *args, **kwargs):
        # Serve from cache (populated by Celery Beat at midnight).
        # If the cache is cold, kick off a background task and return 202.
        cached = cache.get(SCHEDULE_CACHE_KEY)
        if cached:
            return Response(cached, status=status.HTTP_200_OK)
        generate_daily_schedule.delay()
        return Response(
            {"status": "schedule_being_generated", "message": "Generating schedule in background. Retry in ~30 seconds."},
            status=status.HTTP_202_ACCEPTED,
        )


class AnalyticsView(APIView):
    def get(self, request, *args, **kwargs):
        now = timezone.localtime()
        today = now.date()
        week_start = today - timedelta(days=6)

        all_events = ActionableEvent.objects.all()
        week_events = all_events.filter(start_time__date__gte=week_start)
        week_rows = list(
            week_events.values("start_time", "event_type", "duration_minutes", "focus_score", "metadata")
        )

        deep_work_today = week_events.filter(start_time__date=today, event_type__icontains="deep work")
        total_deep_minutes_today = deep_work_today.aggregate(total=Sum("duration_minutes")).get("total") or 0

        focus_today = (
            week_events.filter(start_time__date=today, focus_score__isnull=False)
            .values("start_time", "focus_score")
            .order_by("start_time")
        )
        hour_focus = {}
        for row in focus_today:
            hour = timezone.localtime(row["start_time"]).hour
            bucket = hour_focus.setdefault(hour, {"sum": 0.0, "count": 0})
            bucket["sum"] += float(row["focus_score"])
            bucket["count"] += 1
        best_focus_hour = None
        if hour_focus:
            best_hour = max(hour_focus, key=lambda h: hour_focus[h]["sum"] / hour_focus[h]["count"])
            best_focus_hour = f"{best_hour:02d}:00"

        deep_work_days = set(
            all_events.filter(event_type__icontains="deep work").values_list("start_time__date", flat=True)
        )
        streak = 0
        cursor = today
        while cursor in deep_work_days:
            streak += 1
            cursor = cursor - timedelta(days=1)

        weekly_data = []
        for i in range(7):
            day = week_start + timedelta(days=i)
            day_events = week_events.filter(start_time__date=day).filter(
                Q(event_type__icontains="deep work")
                | Q(event_type__icontains="study")
                | Q(event_type__icontains="algorithm")
            )
            avg_focus = day_events.filter(focus_score__isnull=False).aggregate(avg=Avg("focus_score")).get("avg")
            total_minutes = day_events.aggregate(total=Sum("duration_minutes")).get("total") or 0
            weekly_data.append(
                {
                    "date": day.isoformat(),
                    "avg_focus": round(avg_focus, 2) if avg_focus is not None else None,
                    "total_minutes": int(total_minutes),
                }
            )

        heatmap = [[None for _ in range(24)] for _ in range(7)]
        heatmap_counts = [[0 for _ in range(24)] for _ in range(7)]
        for event in week_events.filter(focus_score__isnull=False).values("start_time", "focus_score"):
            local_time = timezone.localtime(event["start_time"])
            day_index = (local_time.date() - week_start).days
            if 0 <= day_index < 7:
                hour = local_time.hour
                if heatmap[day_index][hour] is None:
                    heatmap[day_index][hour] = 0.0
                heatmap[day_index][hour] += float(event["focus_score"])
                heatmap_counts[day_index][hour] += 1
        for day_index in range(7):
            for hour in range(24):
                if heatmap_counts[day_index][hour] > 0:
                    heatmap[day_index][hour] = round(heatmap[day_index][hour] / heatmap_counts[day_index][hour], 2)

        classification_totals = {"Productive": 0, "Neutral": 0, "Waste": 0}
        activity_rollup: dict[tuple[str, str, str], dict] = defaultdict(
            lambda: {"minutes": 0, "count": 0, "last_seen": None}
        )
        for row in week_rows:
            metadata = row.get("metadata") or {}
            label = metadata.get("raw_title") or row.get("event_type") or "Unknown Activity"
            app = metadata.get("app") or "Unknown"
            classification = classify_event(row.get("event_type"), metadata)
            minutes = int(row.get("duration_minutes") or 0)
            classification_totals[classification] += minutes

            key = (label, app, classification)
            activity_rollup[key]["minutes"] += minutes
            activity_rollup[key]["count"] += 1
            seen = timezone.localtime(row["start_time"]).isoformat()
            if activity_rollup[key]["last_seen"] is None or seen > activity_rollup[key]["last_seen"]:
                activity_rollup[key]["last_seen"] = seen

        detailed_activity = []
        for (label, app, classification), data in activity_rollup.items():
            detailed_activity.append(
                {
                    "label": label,
                    "app": app,
                    "classification": classification,
                    "minutes": int(data["minutes"]),
                    "sessions": int(data["count"]),
                    "last_seen": data["last_seen"],
                }
            )
        detailed_activity.sort(key=lambda item: item["minutes"], reverse=True)
        detailed_activity = detailed_activity[:40]

        category_breakdown = [
            {"name": "Productive", "minutes": classification_totals["Productive"]},
            {"name": "Neutral", "minutes": classification_totals["Neutral"]},
            {"name": "Waste", "minutes": classification_totals["Waste"]},
        ]

        today_rows = [
            row
            for row in week_rows
            if timezone.localtime(row["start_time"]).date() == today
        ]
        today_totals = {"Productive": 0, "Neutral": 0, "Waste": 0}
        for row in today_rows:
            classification = classify_event(row.get("event_type"), row.get("metadata") or {})
            today_totals[classification] += int(row.get("duration_minutes") or 0)
        today_focus_values = [float(row["focus_score"]) for row in today_rows if row.get("focus_score") is not None]
        today_avg_focus = round(sum(today_focus_values) / len(today_focus_values), 2) if today_focus_values else None

        top_waste_item = next((item for item in detailed_activity if item["classification"] == "Waste"), None)
        top_productive_item = next(
            (item for item in detailed_activity if item["classification"] == "Productive"),
            None,
        )

        total_week_minutes = (
            classification_totals["Productive"] + classification_totals["Neutral"] + classification_totals["Waste"]
        )
        productive_share = (
            round((classification_totals["Productive"] / total_week_minutes) * 100, 1)
            if total_week_minutes > 0
            else 0.0
        )
        waste_share = (
            round((classification_totals["Waste"] / total_week_minutes) * 100, 1)
            if total_week_minutes > 0
            else 0.0
        )

        insights_seed = []
        hour_totals = [0.0] * 24
        hour_counts = [0] * 24
        for day_index in range(7):
            for hour in range(24):
                value = heatmap[day_index][hour]
                if value is not None:
                    hour_totals[hour] += value
                    hour_counts[hour] += 1
        hour_avgs = [(hour_totals[h] / hour_counts[h]) if hour_counts[h] > 0 else None for h in range(24)]
        best_window = None
        best_score = None
        for hour in range(23):
            if hour_avgs[hour] is not None and hour_avgs[hour + 1] is not None:
                score = (hour_avgs[hour] + hour_avgs[hour + 1]) / 2
                if best_score is None or score > best_score:
                    best_score = score
                    best_window = hour
        if best_window is not None:
            insights_seed.append(
                f"Your highest focus window this week was {best_window:02d}:00-{best_window + 2:02d}:00."
            )
        if classification_totals["Waste"] > classification_totals["Productive"]:
            insights_seed.append("Waste time is higher than productive time this week. Reduce top waste windows first.")

        context_for_insights = {
            "classification_totals": classification_totals,
            "top_detailed_activity": detailed_activity[:12],
            "weekly_trend": weekly_data,
            "seed_insights": insights_seed,
        }
        llm_insights, insight_source = generate_productivity_insights(context_for_insights)
        assistant_insights = llm_insights or insights_seed or ["Not enough data yet to generate insights."]

        phase1 = build_phase1_output(lookback_days=60)

        payload = {
            "today_snapshot": {
                "total_deep_minutes": int(total_deep_minutes_today),
                "best_focus_hour": best_focus_hour,
                "current_streak": streak,
            },
            "today_analysis": {
                "productive_minutes": today_totals["Productive"],
                "neutral_minutes": today_totals["Neutral"],
                "waste_minutes": today_totals["Waste"],
                "avg_focus_score": today_avg_focus,
                "top_waste_activity": top_waste_item["label"] if top_waste_item else None,
            },
            "week_analysis": {
                "total_minutes": total_week_minutes,
                "productive_share_pct": productive_share,
                "waste_share_pct": waste_share,
                "top_productive_activity": top_productive_item["label"] if top_productive_item else None,
                "top_waste_activity": top_waste_item["label"] if top_waste_item else None,
            },
            "weekly_trend": weekly_data,
            "focus_heatmap": {
                "start_date": week_start.isoformat(),
                "values": heatmap,
            },
            "classification_totals": classification_totals,
            "detailed_activity": detailed_activity,
            "category_breakdown": category_breakdown,
            "assistant_insights": assistant_insights,
            "assistant_insights_source": insight_source,
            "ml_phase1": {
                "feature_store": phase1.feature_store,
                "probabilistic_forecast": phase1.probabilistic_forecast,
                "anomaly_detection": phase1.anomaly_detection,
            },
        }
        return Response(payload, status=status.HTTP_200_OK)


class RegimeView(APIView):
    def get(self, request, *args, **kwargs):
        result = detect_regime(days=42)
        return Response(result, status=status.HTTP_200_OK)


class ClassificationQualityView(APIView):
    def get(self, request, *args, **kwargs):
        result = classification_quality(days=30)
        return Response(result, status=status.HTTP_200_OK)


class RankedScheduleView(APIView):
    def get(self, request, *args, **kwargs):
        result = run_sequence_forecast_and_optimizer(lookback_days=45)
        return Response(result, status=status.HTTP_200_OK)


class DecisionRecommendationView(APIView):
    def get(self, request, *args, **kwargs):
        result = recommend_actions(top_k=2)
        return Response(result, status=status.HTTP_200_OK)


class DecisionUpliftView(APIView):
    def get(self, request, *args, **kwargs):
        result = estimate_uplift()
        return Response(result, status=status.HTTP_200_OK)


class InterventionLogView(APIView):
    def post(self, request, *args, **kwargs):
        action = str(request.data.get("action", "")).strip()
        if not action:
            return Response({"error": "action is required"}, status=status.HTTP_400_BAD_REQUEST)
        record = InterventionLog.objects.create(
            action=action,
            context=request.data.get("context") or {},
            predicted_uplift=float(request.data.get("predicted_uplift", 0.0)),
            reward=float(request.data.get("reward")) if request.data.get("reward") is not None else None,
            accepted=bool(request.data.get("accepted", True)),
            notes=str(request.data.get("notes", "")),
        )
        return Response(
            {
                "status": "logged",
                "id": record.id,
                "action": record.action,
            },
            status=status.HTTP_201_CREATED,
        )


class InfluenceGraphView(APIView):
    def get(self, request, *args, **kwargs):
        rebuild = str(request.query_params.get("rebuild", "0")).lower() in ("1", "true", "yes")
        build_result = None
        if rebuild:
            build_result = rebuild_influence_graph(lookback_days=60)
        summary = graph_summary_and_leverage(top_k=8)
        payload = {
            "build_result": build_result,
            "graph": summary,
        }
        return Response(payload, status=status.HTTP_200_OK)


class PrivacyStatusView(APIView):
    def get(self, request, *args, **kwargs):
        return Response(privacy_status(), status=status.HTTP_200_OK)


class HealthCheckView(APIView):
    """
    GET /api/health/ — checks DB, cache (Redis), and local LLM connectivity.
    Safe to call without authentication; used for monitoring and demo reliability.
    """
    permission_classes = []  # always public
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        import requests as _req
        import os

        # Database
        try:
            db_ok = ActionableEvent.objects.count() >= 0
        except Exception:
            db_ok = False

        # Redis / Cache
        try:
            cache.set("_health_ping", "1", timeout=5)
            redis_ok = cache.get("_health_ping") == "1"
        except Exception:
            redis_ok = False

        # Local LLM (Ollama)
        llm_endpoint = os.environ.get("LOCAL_LLM_ENDPOINT", "http://127.0.0.1:11434/api/generate")
        try:
            llm_resp = _req.get(llm_endpoint.replace("/api/generate", "/api/tags"), timeout=3)
            llm_ok = llm_resp.status_code == 200
        except Exception:
            llm_ok = False

        all_ok = db_ok and redis_ok
        return Response(
            {
                "status": "ok" if all_ok else "degraded",
                "database": "up" if db_ok else "down",
                "redis": "up" if redis_ok else "down",
                "local_llm": "up" if llm_ok else "down",
            },
            status=status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE,
        )
