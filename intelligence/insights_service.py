import json
import os
from typing import Any

import requests


def _fallback_insights(context: dict[str, Any]) -> list[str]:
    insights = []
    totals = context.get("classification_totals", {})
    productive = float(totals.get("Productive", 0))
    waste = float(totals.get("Waste", 0))
    neutral = float(totals.get("Neutral", 0))
    total = productive + waste + neutral

    if total <= 0:
        return ["Not enough activity data yet. Keep tracking for a full day to unlock personalized advice."]

    waste_pct = (waste / total) * 100.0
    productive_pct = (productive / total) * 100.0
    if waste_pct >= 30:
        insights.append(
            f"Waste time is {waste_pct:.0f}% of tracked time. Reduce one high-waste session daily to recover focus time."
        )
    if productive_pct >= 50:
        insights.append(
            f"Productive time is {productive_pct:.0f}% this week. Protect the same high-focus slots every day."
        )
    if neutral > productive:
        insights.append("Neutral time is high. Convert one neutral block into planned deep work each day.")
    if not insights:
        insights.append("Your mix is stable. Shift one neutral block to a pre-planned task for incremental gains.")
    return insights


def _local_llm_insights(context: dict[str, Any]) -> list[str] | None:
    endpoint = os.environ.get("LOCAL_LLM_ENDPOINT", "http://127.0.0.1:11434/api/generate")
    model = os.environ.get("LOCAL_LLM_MODEL", "mistral")
    timeout_seconds = int(os.environ.get("LOCAL_LLM_TIMEOUT_SECONDS", "120"))

    totals = context.get("classification_totals", {})
    top_items = context.get("top_detailed_activity", [])[:3]
    compact = {
        "productive_minutes": totals.get("Productive", 0),
        "neutral_minutes": totals.get("Neutral", 0),
        "waste_minutes": totals.get("Waste", 0),
        "top_activities": [
            {
                "label": item.get("label"),
                "classification": item.get("classification"),
                "minutes": item.get("minutes"),
            }
            for item in top_items
        ],
    }
    prompt = (
        "Return exactly 3 concise insights for productivity improvement.\n"
        "Each line must include one action.\n"
        "Data:\n"
        f"{json.dumps(compact)}"
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 140,
        },
    }
    try:
        response = requests.post(endpoint, json=payload, timeout=timeout_seconds)
        if response.status_code != 200:
            return None
        data = response.json()
        text = str(data.get("response", "")).strip()
        if not text:
            return None
        lines = [line.strip("- ").strip() for line in text.splitlines() if line.strip()]
        cleaned = [line for line in lines if len(line) > 8][:3]
        return cleaned or None
    except requests.RequestException:
        return None


def generate_productivity_insights(context: dict[str, Any]) -> tuple[list[str], str]:
    local = _local_llm_insights(context)
    if local:
        return local, "local_llm"
    return (
        [
            "Local LLM is required for insights but did not respond.",
            "Start your local model server and verify LOCAL_LLM_MODEL is available.",
            "No fallback insights are enabled.",
        ],
        "local_llm_required",
    )
