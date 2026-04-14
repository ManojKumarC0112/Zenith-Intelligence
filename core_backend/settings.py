"""
Django settings for core_backend project.
"""

import os
from pathlib import Path

from celery.schedules import crontab

# ─── Helpers ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent


def _env(key: str, default: str = "") -> str:
    """Read from environment; try loading .env file on first call."""
    return os.environ.get(key, default)


# Attempt to load .env from the project root (works without python-dotenv)
_dotenv_path = BASE_DIR / ".env"
if _dotenv_path.exists():
    with open(_dotenv_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

# ─── Core ─────────────────────────────────────────────────────────────────────
SECRET_KEY = _env(
    "DJANGO_SECRET_KEY",
    # Safe dev-only fallback — override in production via .env
    "django-insecure-dev-only-replace-in-production-!!",
)

DEBUG = _env("DJANGO_DEBUG", "True").lower() not in ("false", "0", "no")

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# ─── Applications ─────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework.authtoken",
    "intelligence",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "core_backend.wsgi.application"

# ─── Database ─────────────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ─── Auth / REST Framework ────────────────────────────────────────────────────
REST_FRAMEWORK = {
    # Token auth for all endpoints; use SessionAuth during local dev via admin
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    # Allow unauthenticated reads/writes in DEBUG for ease of local dev.
    # In production set DEFAULT_PERMISSION_CLASSES to IsAuthenticated.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny" if DEBUG else "rest_framework.permissions.IsAuthenticated"
    ],
}

# ─── Password Validation ──────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ─── Internationalisation ─────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"   # Fixed: was UTC, causing Schedule to be 5.5 h off
USE_I18N = True
USE_TZ = True

# ─── Static Files ─────────────────────────────────────────────────────────────
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─── CORS ─────────────────────────────────────────────────────────────────────
_cors_env = _env("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
CORS_ALLOWED_ORIGINS = [origin.strip() for origin in _cors_env.split(",") if origin.strip()]

# ─── Celery ───────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = _env("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = _env("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

CELERY_BEAT_SCHEDULE = {
    "train-prophet-every-midnight": {
        "task": "intelligence.tasks.generate_daily_schedule",
        "schedule": crontab(minute=0, hour=0),
    },
    "run-phase1-ml-hourly": {
        "task": "intelligence.tasks.run_phase1_ml_pipeline",
        "schedule": crontab(minute=0),
    },
    "run-phase2-embedding-every-2-hours": {
        "task": "intelligence.tasks.run_phase2_representation_pipeline",
        "schedule": crontab(minute=15, hour="*/2"),
    },
    "run-phase3-sequence-every-4-hours": {
        "task": "intelligence.tasks.run_phase3_sequence_optimizer",
        "schedule": crontab(minute=30, hour="*/4"),
    },
    "run-phase4-decisioning-hourly": {
        "task": "intelligence.tasks.run_phase4_decisioning_pipeline",
        "schedule": crontab(minute=45),
    },
    "run-phase5-graph-every-6-hours": {
        "task": "intelligence.tasks.run_phase5_graph_pipeline",
        "schedule": crontab(minute=5, hour="*/6"),
    },
}

# ─── Logging ──────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "focusos.log",
            "maxBytes": 5 * 1024 * 1024,  # 5 MB
            "backupCount": 3,
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "INFO",
    },
    "loggers": {
        "intelligence": {
            "handlers": ["console", "file"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
    },
}
