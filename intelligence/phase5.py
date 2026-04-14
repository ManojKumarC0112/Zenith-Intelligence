from __future__ import annotations

import logging
import os
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any

from django.utils import timezone

from .models import ActionableEvent, HabitInfluenceEdge
from .utils import classify_event

logger = logging.getLogger(__name__)


def _activity_label(event: ActionableEvent) -> str:
    metadata = event.metadata or {}
    raw = str(metadata.get("raw_title", "")).strip()
    if raw:
        return raw[:255]
    return str(event.event_type or "Unknown")[:255]


def _classification(event: ActionableEvent) -> str:
    """Classify a single event using the shared utility."""
    return classify_event(event.event_type, event.metadata or {})


def rebuild_influence_graph(lookback_days: int = 60) -> dict[str, Any]:
    cutoff = timezone.now() - timedelta(days=lookback_days)
    events = list(ActionableEvent.objects.filter(start_time__gte=cutoff).order_by("start_time"))
    if len(events) < 2:
        return {"status": "insufficient_data", "edge_count": 0}

    edge_stats: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "gap_sum": 0.0, "positive": 0.0}
    )
    for idx in range(1, len(events)):
        prev_event = events[idx - 1]
        event = events[idx]
        source = _activity_label(prev_event)
        target = _activity_label(event)
        gap = (event.start_time - prev_event.start_time).total_seconds() / 60.0
        if gap < 0:
            continue
        key = (source, target)
        edge_stats[key]["count"] += 1.0
        edge_stats[key]["gap_sum"] += gap
        if _classification(event) == "Productive":
            edge_stats[key]["positive"] += 1.0

    HabitInfluenceEdge.objects.all().delete()
    created = 0
    for (source, target), stats in edge_stats.items():
        count = int(stats["count"])
        avg_gap = stats["gap_sum"] / max(stats["count"], 1.0)
        positive_impact = stats["positive"] / max(stats["count"], 1.0)
        weight = count * (0.7 + 0.3 * positive_impact) / max(avg_gap, 1.0)
        HabitInfluenceEdge.objects.create(
            source_label=source,
            target_label=target,
            weight=round(weight, 6),
            transition_count=count,
            avg_gap_minutes=round(avg_gap, 2),
            positive_impact=round(positive_impact, 4),
        )
        created += 1

    return {"status": "ok", "edge_count": created}


def graph_summary_and_leverage(top_k: int = 8) -> dict[str, Any]:
    edges = list(HabitInfluenceEdge.objects.all()[:5000])
    if not edges:
        return {"status": "no_graph", "nodes": [], "edges": [], "leverage_recommendations": []}

    out_weight = Counter()
    in_weight = Counter()
    labels = set()
    serialized_edges = []
    for edge in edges:
        labels.add(edge.source_label)
        labels.add(edge.target_label)
        out_weight[edge.source_label] += float(edge.weight)
        in_weight[edge.target_label] += float(edge.weight)
        serialized_edges.append(
            {
                "source": edge.source_label,
                "target": edge.target_label,
                "weight": edge.weight,
                "transition_count": edge.transition_count,
                "positive_impact": edge.positive_impact,
            }
        )

    node_scores = []
    for label in labels:
        score = out_weight[label] * 0.65 + in_weight[label] * 0.35
        node_scores.append({"label": label, "score": round(score, 4)})
    node_scores.sort(key=lambda row: row["score"], reverse=True)

    leverage = []
    for node in node_scores[:top_k]:
        outgoing = [edge for edge in serialized_edges if edge["source"] == node["label"]]
        outgoing.sort(key=lambda edge: edge["weight"], reverse=True)
        top_targets = [edge["target"] for edge in outgoing[:3]]
        leverage.append(
            {
                "anchor_activity": node["label"],
                "influence_score": node["score"],
                "likely_impacted_activities": top_targets,
                "recommendation": (
                    f"Stabilize '{node['label']}' first; it likely shifts {len(top_targets)} linked activities."
                ),
            }
        )

    return {
        "status": "ok",
        "nodes": node_scores[:40],
        "edges": serialized_edges[:120],
        "leverage_recommendations": leverage,
    }


def privacy_status() -> dict[str, Any]:
    local_only = os.environ.get("LOCAL_ONLY_TRAINING", "1").strip() not in ("0", "false", "False")
    local_llm_endpoint = os.environ.get("LOCAL_LLM_ENDPOINT", "http://127.0.0.1:11434/api/generate")
    return {
        "local_only_training": local_only,
        "local_llm_endpoint": local_llm_endpoint,
        "cloud_training_enabled": False if local_only else True,
        "note": "Set LOCAL_ONLY_TRAINING=1 to force all learning and inference to stay on-device.",
    }
