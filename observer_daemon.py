"""
observer_daemon.py — Silent Observer

Runs as a background process. Every 60 seconds it reads the active
window title, classifies the activity, accumulates duration, and
POSTs the event to the Django API when the activity changes.

Resilience: if the Django server is offline, events are written to
offline_buffer.jsonl and flushed automatically on the next successful
connection.
"""

import json
import logging
import logging.handlers
import pathlib
import time
from datetime import datetime, timezone as dt_timezone

import pygetwindow as gw
import requests


# ─── Configuration ────────────────────────────────────────────────────────────
DJANGO_API_URL = "http://127.0.0.1:8000/ingest/"
CHECK_INTERVAL_SECONDS = 60
MIN_LOG_DURATION_MINUTES = 2
OFFLINE_BUFFER = pathlib.Path("offline_buffer.jsonl")

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            "observer.log", maxBytes=2 * 1024 * 1024, backupCount=2
        ),
    ],
)
logger = logging.getLogger("observer")

# ─── Keyword Lists ────────────────────────────────────────────────────────────
WASTE_KEYWORDS = [
    "instagram", "netflix", "amazon prime", "prime video", "disney",
    "hotstar", "spotify", "twitch", "reddit", "facebook", "x.com",
    "twitter", "tiktok", "anime", "crunchyroll", "hulu", "movie",
    "movies", "game", "steam", "epic games",
]

YOUTUBE_PRODUCTIVE_KEYWORDS = [
    "tutorial", "course", "lecture", "lesson", "review", "explained",
    "documentation", "system design", "machine learning", "deep learning",
    "data structures", "algorithms", "leetcode",
]

PRODUCTIVE_APPS = [
    "visual studio code", "pycharm", "cursor", "neovim", "vim",
    "jupyter", "intellij", "sublime text", "atom",
]


# ─── Activity Categorisation ──────────────────────────────────────────────────

def extract_app_name(window_title: str) -> str:
    if " - " in window_title:
        return window_title.split(" - ")[-1].strip()
    return window_title.strip() or "Unknown"


def categorize_activity(window_title: str):
    """Return (event_type, metadata) or (None, None) if unclassifiable."""
    if not window_title:
        return None, None

    title = window_title.lower()
    app_name = extract_app_name(window_title)

    # — Coding / IDE —
    if any(app in title for app in PRODUCTIVE_APPS):
        return "Deep Work", {
            "platform": "IDE",
            "context": "Coding",
            "classification": "Productive",
            "app": app_name,
            "raw_title": window_title,
        }

    # — Algorithm practice —
    if "leetcode" in title or "neetcode" in title:
        return "Algorithm Practice", {
            "platform": "Browser",
            "context": "Interview Prep",
            "classification": "Productive",
            "app": app_name,
            "raw_title": window_title,
        }

    # — Study / PDF / academic material —
    if ".pdf" in title or "operating systems" in title or "dbms" in title:
        return "Study", {
            "platform": "PDF/Notes",
            "context": "University Curriculum",
            "classification": "Productive",
            "app": app_name,
            "raw_title": window_title,
        }

    # — YouTube: productive vs neutral —
    if "youtube" in title:
        for keyword in YOUTUBE_PRODUCTIVE_KEYWORDS:
            if keyword in title:
                return "Study", {
                    "platform": "YouTube",
                    "context": "Learning",
                    "classification": "Productive",
                    "trigger": keyword,
                    "app": app_name,
                    "raw_title": window_title,
                }
        return "Neutral", {
            "classification": "Neutral",
            "platform": "YouTube",
            "app": app_name,
            "raw_title": window_title,
        }

    # — Known waste sites —
    for keyword in WASTE_KEYWORDS:
        if keyword in title:
            return "Waste", {
                "classification": "Waste",
                "trigger": keyword,
                "app": app_name,
                "raw_title": window_title,
            }

    return "Neutral", {
        "classification": "Neutral",
        "app": app_name,
        "raw_title": window_title,
    }


# ─── Offline Buffer ───────────────────────────────────────────────────────────

def _buffer_event(payload: dict) -> None:
    """Write an event to the local JSONL buffer when API is unreachable."""
    with OFFLINE_BUFFER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) + "\n")
    logger.warning("Buffered offline event: %s (%dm)", payload["event_type"], payload["duration_minutes"])


def _flush_buffer() -> None:
    """Attempt to send buffered offline events to the API."""
    if not OFFLINE_BUFFER.exists():
        return
    lines = OFFLINE_BUFFER.read_text(encoding="utf-8").strip().splitlines()
    if not lines:
        OFFLINE_BUFFER.unlink(missing_ok=True)
        return

    sent = 0
    remaining = []
    for line in lines:
        try:
            payload = json.loads(line)
            resp = requests.post(DJANGO_API_URL, json=payload, timeout=10)
            if resp.status_code == 201:
                sent += 1
            else:
                remaining.append(line)
        except requests.RequestException:
            remaining.append(line)

    if remaining:
        OFFLINE_BUFFER.write_text("\n".join(remaining) + "\n", encoding="utf-8")
    else:
        OFFLINE_BUFFER.unlink(missing_ok=True)

    if sent:
        logger.info("Flushed %d buffered event(s) to API.", sent)


# ─── API Sender ───────────────────────────────────────────────────────────────

def send_to_brain(event_type: str, duration: int, metadata: dict) -> None:
    payload = {
        "event_type": event_type,
        "duration_minutes": duration,
        "metadata": metadata,
        "start_time": datetime.now(dt_timezone.utc).isoformat(),
    }
    # First try to flush anything buffered from previous offline periods
    _flush_buffer()
    try:
        response = requests.post(DJANGO_API_URL, json=payload, timeout=10)
        if response.status_code == 201:
            logger.info("Logged %dm of '%s'", duration, event_type)
        else:
            logger.error("API rejected payload (HTTP %s): %s", response.status_code, response.text[:200])
    except requests.exceptions.ConnectionError:
        logger.warning("Django server offline — buffering event locally.")
        _buffer_event(payload)
    except requests.exceptions.RequestException as exc:
        logger.error("Failed to send event: %s", exc)
        _buffer_event(payload)


# ─── Main Loop ────────────────────────────────────────────────────────────────

logger.info("FocusOS Silent Observer starting…")
current_activity = None
current_metadata = None
duration_minutes = 0

while True:
    try:
        active_window = gw.getActiveWindow()
        window_title = active_window.title if active_window else ""

        new_activity, new_metadata = categorize_activity(window_title)
        logger.debug("title='%s' → activity=%s duration=%dm", window_title, new_activity, duration_minutes)

        if new_activity:
            if new_activity == current_activity:
                duration_minutes += 1
            else:
                if current_activity and duration_minutes >= MIN_LOG_DURATION_MINUTES:
                    send_to_brain(current_activity, duration_minutes, current_metadata)
                current_activity = new_activity
                current_metadata = new_metadata
                duration_minutes = 1
        else:
            if current_activity and duration_minutes >= MIN_LOG_DURATION_MINUTES:
                send_to_brain(current_activity, duration_minutes, current_metadata)
            current_activity = None
            current_metadata = None
            duration_minutes = 0

    except Exception as exc:
        logger.exception("Unexpected error in observer loop: %s", exc)

    time.sleep(CHECK_INTERVAL_SECONDS)
