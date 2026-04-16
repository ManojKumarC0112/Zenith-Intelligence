# Zenith-Intelligence — Personal Intelligence Engine

> *An AI-native, privacy-first productivity system that observes your computer behaviour, learns your cognitive patterns, and tells you exactly when and what to work on next — without sending a single byte to the cloud.*

---

## Why This Is Not a To-Do App

A to-do app asks you to remember what you need to do.  
**Zenith-Intelligence watches what you actually do, builds a machine learning model of your behaviour, and proactively coaches you.**

| Feature | Typical To-Do App | FocusOS |
|---|---|---|
| Data input | Manual entry by user | Passive OS-level window observer |
| Intelligence | None | 5-phase ML pipeline |
| Scheduling | User picks times | Prophet time-series + Bayesian optimiser |
| Coaching | Reminders | LLM-generated insights from real activity |
| Privacy | Cloud-synced | 100 % on-device (Ollama + SQLite) |
| Behavioural modelling | ❌ | Habit influence graph + causal uplift |

---

## What It Does

Zenith-Intelligence runs two persistent background processes:

1. **Silent Observer** (`observer_daemon.py`) — Polls the active window title every 60 seconds, classifies the activity (Productive / Neutral / Waste), accumulates duration, and streams the event to the Django API. Offline resilience: events are buffered locally and flushed automatically when the server reconnects.

2. **Intelligence Engine** (`intelligence/`) — A Django REST API with five ML phases that run on a Celery schedule, continuously learning from your activity history.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Your Windows PC                              │
│                                                                     │
│  ┌──────────────────┐     POST /ingest/    ┌─────────────────────┐ │
│  │ observer_daemon  │ ──────────────────▶  │  Django REST API    │ │
│  │ (pygetwindow)    │  (offline-buffered)  │  port 8000          │ │
│  └──────────────────┘                      └────────┬────────────┘ │
│                                                     │               │
│                                              SQLite DB              │
│                                         (ActionableEvent,           │
│                                          ActivityEmbedding,         │
│                                          RegimeSnapshot,            │
│                                          InterventionLog,           │
│                                          HabitInfluenceEdge)        │
│                                                     │               │
│  ┌──────────────────────────────────────────────────┼──────────┐   │
│  │              Celery Beat (scheduled ML pipeline) │          │   │
│  │                                                  ▼          │   │
│  │  Phase 1 (hourly)  ─── Feature engineering + anomaly detect │   │
│  │  Phase 2 (2h)      ─── Embedding + clustering + regime      │   │
│  │  Phase 3 (4h)      ─── Sequence forecast + schedule optim.  │   │
│  │  Phase 4 (hourly)  ─── UCB1 bandit + causal uplift          │   │
│  │  Phase 5 (6h)      ─── Habit influence graph rebuild        │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                     │               │
│  ┌──────────────────┐    GET /api/*        ┌────────┴────────────┐ │
│  │ Next.js 16 UI    │ ◀─────────────────── │  Analytics API      │ │
│  │ intelligence-ui/ │                      └─────────────────────┘ │
│  └──────────────────┘                                              │
│                                                     │               │
│  ┌──────────────────┐                      ┌────────┴────────────┐ │
│  │  Ollama (Mistral)│ ◀─────────────────── │  Insights Service   │ │
│  │  Local LLM       │                      │  (on-device AI)     │ │
│  └──────────────────┘                      └─────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## ML Pipeline — 5 Phases

### Phase 1 · Feature Engineering & Anomaly Detection
**File:** `intelligence/ml_phase1.py`

Builds a fully featured Pandas DataFrame from raw event history:
- Time features: `hour`, `weekday`, `break_minutes`, `app_switch`
- Productivity flags: `is_productive`, `is_waste`
- **Probabilistic focus forecast** — per-hour quantile regression (P10 / P50 / P90) over a 24-hour horizon
- **Anomaly detection** — Z-score comparison of recent 7 days vs baseline 21 days. Surfaces burnout risk signals early.

### Phase 2 · Representation Learning & Regime Detection
**File:** `intelligence/phase2.py`

- **Text embedding** — Uses `sentence-transformers/all-MiniLM-L6-v2` (falls back to deterministic hash-embedding if unavailable) to convert window titles + metadata into dense 64-dim vectors
- **Prototype-based classifier** — Builds per-class centroids, computes cosine similarity, applies softmax, falls back to keyword matching below confidence threshold 0.45
- **Behaviour regime detection** — Pseudo-Bayesian sigmoid scoring over 42 days of data classifies your current period as `normal`, `exam`, or `burnout`. Stored daily in `RegimeSnapshot`.

### Phase 3 · Sequence Forecast & Schedule Optimiser
**File:** `intelligence/phase3.py`

- **24-hour focus forecast** — Weighted blend of hour-of-day historical average and recent trailing mean, with a waste-activity penalty
- **Schedule optimiser** — Scores each forecast slot on a tradeoff: `focus_gain + productive_potential − fatigue_cost − waste_risk`. Top 8 blocks returned with regime-aware task suggestions.

### Phase 4 · Contextual Decisioning (UCB1 Bandit)
**File:** `intelligence/phase4.py`

Implements a **UCB1 contextual multi-armed bandit** over a dynamic action space that auto-discovers new actions from the `InterventionLog` table.

UCB1 formula: `score = prior(context) + mean_reward + sqrt(2 · ln(N+1) / (n+1))`

- **Prior** is regime-aware (exam → boost deep work; burnout → boost break; waste > 20 min → boost social blocker)
- **Causal uplift estimation** — Compares treated group (action was taken) mean reward against population baseline reward. Surfaces which interventions actually moved the needle.

### Phase 5 · Habit Influence Graph
**File:** `intelligence/phase5.py`

Builds a directed weighted graph of activity transitions from 60 days of history:

- **Nodes** = unique activity labels (raw window titles)
- **Edges** = `weight = transition_count × (0.7 + 0.3 × positive_impact) / avg_gap_time`
- **Leverage recommendations** — Identifies anchor activities (high out-weight) and predicts which downstream activities will shift if the anchor is stabilised

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 5.2 + Django REST Framework |
| Task Queue | Celery + Redis |
| Time-Series ML | Facebook Prophet |
| Embeddings | `sentence-transformers` (all-MiniLM-L6-v2) |
| Numerical ML | NumPy + Pandas |
| Language Model | Ollama (Mistral 7B — 100% local) |
| Database | SQLite (zero-config, portable) |
| OS Observer | `pygetwindow` |
| Frontend | Next.js 16 (Turbopack) |
| Language | Python 3.11+ |

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/ingest/` | Ingest a tracked activity event |
| `GET` | `/api/analytics/` | Full weekly analytics dashboard payload |
| `GET` | `/api/analytics/regime/` | Current behaviour regime (normal/exam/burnout) |
| `GET` | `/api/analytics/classification-quality/` | Embedding classifier proxy accuracy |
| `GET` | `/api/schedule/` | Today's peak focus schedule (cache-first, async) |
| `GET` | `/api/schedule/ranked/` | Ranked 24-hour schedule blocks with tradeoff scores |
| `GET` | `/api/decision/recommend/` | UCB1 bandit action recommendations |
| `GET` | `/api/decision/uplift/` | Causal uplift per intervention type |
| `POST` | `/api/decision/log/` | Log an intervention + reward signal |
| `GET` | `/api/graph/influence/` | Habit influence graph + leverage recommendations |
| `GET` | `/api/privacy/status/` | On-device vs cloud mode status |
| `GET` | `/api/health/` | Service health — DB, Redis, Ollama |

---

## Getting Started

### Prerequisites

| Requirement | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Backend |
| Node.js | 18+ | Frontend |
| Redis | Any | Celery broker |
| Ollama | Latest | Local LLM |

### 1. Clone and install

```bash
git clone https://github.com/your-username/focusos.git
cd focusos
python -m venv venv
.\venv\Scripts\activate        # Windows
pip install django djangorestframework celery redis pandas numpy \
            prophet sentence-transformers pygetwindow requests \
            django-cors-headers
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — set DJANGO_SECRET_KEY to a long random string
```

### 3. Start services

```bash
# Terminal 1 — Django API
python manage.py migrate
python manage.py runserver

# Terminal 2 — Celery worker
celery -A core_backend worker -l info

# Terminal 3 — Celery Beat (scheduler)
celery -A core_backend beat -l info

# Terminal 4 — Silent Observer
python observer_daemon.py

# Terminal 5 — Ollama LLM
ollama run mistral

# Terminal 6 — Next.js UI
cd intelligence-ui
npm install
npm run dev
```

### 4. Verify everything is running

```bash
curl http://localhost:8000/api/health/
# Expected: {"status": "ok", "database": "up", "redis": "up", "local_llm": "up"}
```

### 5. Run tests

```bash
python manage.py test intelligence
```

---

## Data Models

```
ActionableEvent          ActivityEmbedding          RegimeSnapshot
─────────────────        ──────────────────         ──────────────
event_type               event (FK)                 snapshot_date (unique)
start_time               text_input                 regime_label
duration_minutes         embedding (JSON)           regime_score
focus_score              predicted_class            details (JSON)
metadata (JSON)          confidence
                         used_fallback
                         cluster_id
                         classifier_version

InterventionLog          HabitInfluenceEdge
───────────────          ──────────────────
action                   source_label
context (JSON)           target_label
predicted_uplift         weight
reward                   transition_count
accepted                 avg_gap_minutes
notes                    positive_impact
```

---

## Privacy by Design

FocusOS is built with an explicit privacy contract:

- **No cloud training** — All ML models train locally on your data. `LOCAL_ONLY_TRAINING=1` is the default.
- **No external APIs** — The LLM (Mistral via Ollama) runs fully on your machine.
- **No telemetry** — Zero analytics, zero tracking beacons.
- **Local-only database** — SQLite file lives on your machine.
- **You own your data** — Export or delete at any time via the Django admin panel.

Check current privacy status anytime: `GET /api/privacy/status/`

---

## Project Structure

```
focusos/
├── core_backend/          Django project configuration
│   ├── settings.py        Env-driven config (secret key, TZ, CORS, Celery)
│   ├── celery.py          Celery app definition
│   └── urls.py            Root URL routing
├── intelligence/          ML intelligence app
│   ├── models.py          5 data models
│   ├── utils.py           Shared classification utility
│   ├── ml_phase1.py       Feature engineering + anomaly detection
│   ├── phase2.py          Embedding + clustering + regime detection
│   ├── phase3.py          Sequence forecast + schedule optimiser
│   ├── phase4.py          UCB1 bandit + causal uplift
│   ├── phase5.py          Habit influence graph
│   ├── insights_service.py  Ollama LLM integration (graceful fallback)
│   ├── tasks.py           Celery scheduled tasks
│   ├── views.py           REST API views + health check
│   ├── urls.py            App URL patterns
│   └── tests.py           Unit test suite
├── intelligence-ui/       Next.js 16 dashboard
├── observer_daemon.py     OS-level activity monitor (offline-buffered)
├── .env.example           Environment variable documentation
└── .gitignore
```

---

## Roadmap

- [ ] System-tray pop-up for focus score input (1–10) every 30 mins
- [ ] CSV / JSON export endpoint (`GET /api/export/`)
- [ ] Pomodoro mode with auto-log on session completion
- [ ] Cross-platform observer (macOS / Linux via `Xlib`)
- [ ] Weekly email digest (local SMTP)

---

## Author

**Manoj Kumar C** — Computer Science undergraduate  
Built as a self-directed systems + ML learning project.

*"Most productivity apps tell you what to do. FocusOS learns who you are."*
