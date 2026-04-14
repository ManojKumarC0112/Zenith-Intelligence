import hashlib
import logging
import math
import os
import re
from collections import Counter
from datetime import timedelta
from typing import Iterable

import numpy as np
from django.utils import timezone

from .models import ActionableEvent, ActivityEmbedding, RegimeSnapshot
from .utils import classify_event as _classify_shared

logger = logging.getLogger(__name__)

EMBED_DIM = 64
CLASS_NAMES = ("Productive", "Neutral", "Waste")


def _event_text(event: ActionableEvent) -> str:
    metadata = event.metadata or {}
    raw = str(metadata.get("raw_title", "")).strip()
    app = str(metadata.get("app", "")).strip()
    context = str(metadata.get("context", "")).strip()
    pieces = [event.event_type or "", raw, app, context, str(metadata)]
    return " | ".join([piece for piece in pieces if piece])


def _heuristic_label(event: ActionableEvent) -> str:
    """Classify a single event using the shared utility."""
    return _classify_shared(event.event_type, event.metadata or {})


def _keyword_fallback(text: str) -> tuple[str, float]:
    lowered = text.lower()
    waste_terms = (
        "instagram",
        "netflix",
        "tiktok",
        "reddit",
        "spotify",
        "youtube - home",
        "reels",
    )
    productive_terms = (
        "leetcode",
        "system design",
        "deep work",
        "study",
        "course",
        "lecture",
        "tutorial",
    )
    if any(token in lowered for token in waste_terms):
        return "Waste", 0.55
    if any(token in lowered for token in productive_terms):
        return "Productive", 0.58
    return "Neutral", 0.45


def _hash_embed(text: str, dim: int = EMBED_DIM) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    if not tokens:
        return vec
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:2], "little") % dim
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def _load_sentence_model():
    model_name = os.environ.get("SENTENCE_TRANSFORMER_MODEL", "all-MiniLM-L6-v2")
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(model_name)
    except Exception:
        return None


def _embed_texts(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, EMBED_DIM), dtype=np.float32)
    model = _load_sentence_model()
    if model is not None:
        try:
            emb = model.encode(texts, normalize_embeddings=True)
            return np.asarray(emb, dtype=np.float32)
        except Exception:
            pass
    return np.vstack([_hash_embed(text) for text in texts])


def _softmax(values: np.ndarray) -> np.ndarray:
    exp = np.exp(values - np.max(values))
    denom = np.sum(exp)
    if denom <= 0:
        return np.zeros_like(values)
    return exp / denom


def _simple_kmeans(vectors: np.ndarray, k: int = 3, steps: int = 10) -> list[int]:
    if len(vectors) == 0:
        return []
    k = max(1, min(k, len(vectors)))
    centroids = vectors[:k].copy()
    labels = np.zeros(len(vectors), dtype=np.int32)
    for _ in range(steps):
        sims = vectors @ centroids.T
        labels = np.argmax(sims, axis=1)
        new_centroids = []
        for idx in range(k):
            members = vectors[labels == idx]
            if len(members) == 0:
                new_centroids.append(centroids[idx])
                continue
            center = np.mean(members, axis=0)
            norm = np.linalg.norm(center)
            new_centroids.append(center / norm if norm > 0 else center)
        centroids = np.vstack(new_centroids)
    return labels.tolist()


def run_representation_pipeline(days: int = 45) -> dict:
    cutoff = timezone.now() - timedelta(days=days)
    events = list(ActionableEvent.objects.filter(start_time__gte=cutoff).order_by("start_time"))
    if not events:
        return {"status": "no_events", "processed": 0}

    texts = [_event_text(event) for event in events]
    vectors = _embed_texts(texts)
    heuristic_labels = [_heuristic_label(event) for event in events]

    class_proto = {}
    for class_name in CLASS_NAMES:
        idxs = [i for i, label in enumerate(heuristic_labels) if label == class_name]
        if idxs:
            proto = np.mean(vectors[idxs], axis=0)
            norm = np.linalg.norm(proto)
            class_proto[class_name] = proto / norm if norm > 0 else proto
        else:
            class_proto[class_name] = np.zeros(vectors.shape[1], dtype=np.float32)

    labels = _simple_kmeans(vectors, k=3, steps=8)
    processed = 0
    fallback_count = 0
    predictions = []
    confidences = []

    for idx, event in enumerate(events):
        vector = vectors[idx]
        sims = np.array([float(vector @ class_proto[name]) for name in CLASS_NAMES], dtype=np.float32)
        probs = _softmax(sims)
        pred_idx = int(np.argmax(probs))
        pred_label = CLASS_NAMES[pred_idx]
        confidence = float(probs[pred_idx])
        used_fallback = False
        if confidence < 0.45:
            pred_label, confidence = _keyword_fallback(texts[idx])
            used_fallback = True
            fallback_count += 1

        ActivityEmbedding.objects.update_or_create(
            event=event,
            defaults={
                "text_input": texts[idx],
                "embedding": vector.round(6).tolist(),
                "predicted_class": pred_label,
                "confidence": round(confidence, 4),
                "used_fallback": used_fallback,
                "cluster_id": int(labels[idx]) if idx < len(labels) else None,
                "classifier_version": "phase2-v1",
            },
        )
        processed += 1
        predictions.append(pred_label)
        confidences.append(confidence)

    return {
        "status": "ok",
        "processed": processed,
        "fallback_count": fallback_count,
        "class_distribution": dict(Counter(predictions)),
        "avg_confidence": round(float(np.mean(confidences)), 4) if confidences else 0.0,
    }


def detect_regime(days: int = 42) -> dict:
    cutoff = timezone.now() - timedelta(days=days)
    events = list(ActionableEvent.objects.filter(start_time__gte=cutoff))
    if len(events) < 8:
        snapshot = RegimeSnapshot.objects.update_or_create(
            snapshot_date=timezone.localdate(),
            defaults={
                "regime_label": "insufficient_data",
                "regime_score": 0.0,
                "details": {"event_count": len(events)},
            },
        )[0]
        return {
            "regime_label": snapshot.regime_label,
            "regime_score": snapshot.regime_score,
            "details": snapshot.details,
        }

    daily = {}
    for event in events:
        day = timezone.localtime(event.start_time).date()
        row = daily.setdefault(day, {"productive": 0, "waste": 0, "focus": []})
        label = _heuristic_label(event)
        minutes = int(event.duration_minutes or 0)
        if label == "Productive":
            row["productive"] += minutes
        if label == "Waste":
            row["waste"] += minutes
        if event.focus_score is not None:
            row["focus"].append(float(event.focus_score))

    ordered_days = sorted(daily.keys())
    prod = np.array([daily[day]["productive"] for day in ordered_days], dtype=np.float32)
    waste = np.array([daily[day]["waste"] for day in ordered_days], dtype=np.float32)
    focus_values = [score for day in ordered_days for score in daily[day]["focus"]]

    if len(prod) < 8:
        label = "insufficient_data"
        score = 0.0
        details = {"days": len(prod)}
    else:
        split = max(7, len(prod) // 2)
        baseline_prod = prod[:split]
        recent_prod = prod[-7:]
        baseline_waste = waste[:split]
        recent_waste = waste[-7:]

        mean_base = float(np.mean(baseline_prod))
        std_base = float(np.std(baseline_prod))
        mean_recent = float(np.mean(recent_prod))
        waste_base = float(np.mean(baseline_waste))
        waste_recent = float(np.mean(recent_waste))
        waste_delta = waste_recent - waste_base
        focus_avg = float(np.mean(focus_values)) if focus_values else 0.0

        change = mean_recent - mean_base
        sigma = std_base if std_base > 1e-6 else 1.0
        change_score = 1.0 / (1.0 + math.exp(-change / sigma))  # pseudo bayesian probability

        label = "normal"
        regime_score = 0.5
        if change < -0.6 * sigma and waste_delta > 15:
            label = "burnout"
            regime_score = min(0.95, 0.55 + abs(change) / max(30.0, sigma))
        elif change > 0.6 * sigma and focus_avg >= 7.0:
            label = "exam"
            regime_score = min(0.95, 0.55 + change / max(30.0, sigma))
        details = {
            "baseline_productive_mean": round(mean_base, 2),
            "recent_productive_mean": round(mean_recent, 2),
            "baseline_waste_mean": round(waste_base, 2),
            "recent_waste_mean": round(waste_recent, 2),
            "change_score": round(change_score, 3),
            "avg_focus": round(focus_avg, 2),
            "days_observed": len(prod),
        }
        score = round(float(regime_score), 3)

    snapshot = RegimeSnapshot.objects.update_or_create(
        snapshot_date=timezone.localdate(),
        defaults={"regime_label": label, "regime_score": score, "details": details},
    )[0]
    return {
        "regime_label": snapshot.regime_label,
        "regime_score": snapshot.regime_score,
        "details": snapshot.details,
    }


def classification_quality(days: int = 30) -> dict:
    cutoff = timezone.now() - timedelta(days=days)
    records = list(
        ActivityEmbedding.objects.select_related("event").filter(updated_at__gte=cutoff).order_by("-updated_at")
    )
    if not records:
        return {"status": "no_embeddings", "sample_size": 0}

    hits = 0
    fallback_count = 0
    confidences = []
    distribution = Counter()
    mismatches = []
    for record in records:
        heuristic = _heuristic_label(record.event)
        predicted = record.predicted_class
        if predicted == heuristic:
            hits += 1
        else:
            mismatches.append(
                {
                    "event_id": record.event_id,
                    "predicted": predicted,
                    "heuristic": heuristic,
                    "confidence": round(float(record.confidence), 3),
                    "text": record.text_input[:120],
                }
            )
        if record.used_fallback:
            fallback_count += 1
        confidences.append(float(record.confidence))
        distribution[predicted] += 1

    sample = len(records)
    return {
        "status": "ok",
        "sample_size": sample,
        "proxy_accuracy": round(hits / sample, 4),
        "avg_confidence": round(float(np.mean(confidences)), 4),
        "fallback_rate": round(fallback_count / sample, 4),
        "class_distribution": dict(distribution),
        "top_mismatches": mismatches[:10],
    }
