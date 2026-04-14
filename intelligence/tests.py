"""
intelligence/tests.py — Core unit tests for the FocusOS Intelligence Engine.

Run with:  python manage.py test intelligence
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .ml_phase1 import anomaly_summary, build_feature_frame, probabilistic_forecast
from .models import ActionableEvent, InterventionLog
from .phase4 import _get_action_space, estimate_uplift, recommend_actions
from .utils import classify_event


# ─────────────────────────────────────────────────────────────────────────────
# 1. classify_event — shared classification utility
# ─────────────────────────────────────────────────────────────────────────────

class ClassifyEventTests(TestCase):
    def test_metadata_explicit_productive(self):
        self.assertEqual(classify_event("random", {"classification": "productive"}), "Productive")

    def test_metadata_explicit_waste(self):
        self.assertEqual(classify_event("random", {"classification": "waste"}), "Waste")

    def test_metadata_explicit_neutral(self):
        self.assertEqual(classify_event("random", {"classification": "neutral"}), "Neutral")

    def test_event_type_deep_work_keyword(self):
        self.assertEqual(classify_event("Deep Work Session", {}), "Productive")

    def test_event_type_study_keyword(self):
        self.assertEqual(classify_event("Study — OS Chapter 5", {}), "Productive")

    def test_event_type_algorithm_keyword(self):
        self.assertEqual(classify_event("Algorithm Practice on LeetCode", {}), "Productive")

    def test_event_type_waste_keyword(self):
        self.assertEqual(classify_event("Waste — Netflix binge", {}), "Waste")

    def test_unknown_defaults_to_neutral(self):
        self.assertEqual(classify_event("Random Window Title", {}), "Neutral")

    def test_empty_event_type_defaults_to_neutral(self):
        self.assertEqual(classify_event("", {}), "Neutral")

    def test_metadata_overrides_event_type(self):
        # Metadata classification always wins over event_type keywords
        self.assertEqual(classify_event("Deep Work", {"classification": "waste"}), "Waste")

    def test_case_insensitive_metadata(self):
        self.assertEqual(classify_event("x", {"classification": "PRODUCTIVE"}), "Productive")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Phase 1 — feature frame & anomaly detection on empty DB
# ─────────────────────────────────────────────────────────────────────────────

class Phase1EmptyDBTests(TestCase):
    def test_feature_frame_empty(self):
        import pandas as pd
        frame = build_feature_frame(lookback_days=60)
        self.assertIsInstance(frame, pd.DataFrame)
        self.assertTrue(frame.empty)

    def test_probabilistic_forecast_empty(self):
        import pandas as pd
        result = probabilistic_forecast(pd.DataFrame())
        self.assertEqual(result, [])

    def test_anomaly_summary_empty(self):
        import pandas as pd
        result = anomaly_summary(pd.DataFrame())
        self.assertEqual(result["status"], "insufficient_data")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Phase 4 — action space and recommendations
# ─────────────────────────────────────────────────────────────────────────────

class Phase4ActionSpaceTests(TestCase):
    def test_default_action_space_present(self):
        """Default actions must always be present even with empty DB."""
        space = _get_action_space()
        self.assertIn("start_deep_work", space)
        self.assertIn("short_break", space)
        self.assertIn("block_social_app", space)

    def test_custom_action_discovered_from_db(self):
        InterventionLog.objects.create(
            action="go_for_walk",
            predicted_uplift=5.0,
        )
        space = _get_action_space()
        self.assertIn("go_for_walk", space)

    def test_recommend_actions_returns_top_k(self):
        result = recommend_actions(top_k=2)
        self.assertIn("recommended_actions", result)
        self.assertLessEqual(len(result["recommended_actions"]), 2)

    def test_estimate_uplift_insufficient_data(self):
        result = estimate_uplift()
        self.assertEqual(result["status"], "insufficient_data")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Ingest API — smoke test via Django test client
# ─────────────────────────────────────────────────────────────────────────────

class IngestAPITests(TestCase):
    def test_post_valid_event_returns_201(self):
        payload = {
            "event_type": "Deep Work",
            "duration_minutes": 45,
            "metadata": {"classification": "Productive"},
        }
        response = self.client.post(
            "/ingest/",
            data=payload,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(ActionableEvent.objects.count(), 1)

    def test_post_missing_required_field_returns_400(self):
        response = self.client.post(
            "/ingest/",
            data={"event_type": "Deep Work"},  # missing duration_minutes
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Health check endpoint
# ─────────────────────────────────────────────────────────────────────────────

class HealthCheckAPITests(TestCase):
    def test_health_endpoint_exists(self):
        response = self.client.get("/api/health/")
        # Should return 200 or 503 — never 404
        self.assertIn(response.status_code, [200, 503])

    def test_health_response_has_expected_keys(self):
        response = self.client.get("/api/health/")
        data = response.json()
        self.assertIn("status", data)
        self.assertIn("database", data)
