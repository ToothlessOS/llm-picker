"""
Django settings for llm_picker_backend project.

Every secret and every environment-specific value is read from the environment,
with a development-safe default, so that the same settings module runs on a
laptop and in a container without edits. `backend/.env.example` lists the full
set; `backend/.env` (gitignored) is what `load_dotenv` actually reads.
"""

import os
from pathlib import Path

from celery.schedules import crontab
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Read `backend/.env` before any setting below looks at the environment. Not
# `override=True`: a real environment variable must always beat the file, so a
# container can inject `AA_API_KEY` without it being shadowed by a stale checkout.
load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None else value.strip()


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def env_list(name: str, default: tuple[str, ...] = ()) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    "django-insecure-3dea!^igmrfad3!$3wfdamf&g_i&6$*wsy+4ma0s*5f*u=od%a",
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
    ("localhost", "127.0.0.1", "[::1]") if DEBUG else (),
)


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    # Registered so its `DatabaseScheduler` and the `PeriodicTask` admin are
    # available. The schedule itself is declared in code (below) and
    # materialized into editable rows, which keeps it code-reviewable.
    "django_celery_beat",
    "leaderboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # CorsMiddleware must precede CommonMiddleware so that CORS headers survive
    # a redirect or a 404 produced by the common middleware.
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "llm_picker_backend.urls"

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

WSGI_APPLICATION = "llm_picker_backend.wsgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            # The Celery worker writes while `runserver` reads the same file.
            # Without a busy timeout the reader gets an immediate
            # "database is locked"; without IMMEDIATE the write transaction
            # upgrades its lock mid-flight and can fail to upgrade at all.
            # Combined with WAL (enabled in `LeaderboardConfig.ready`), this is
            # what stops the API observing a half-written refresh.
            "timeout": env_int("SQLITE_TIMEOUT_SECONDS", 20),
            "transaction_mode": "IMMEDIATE",
        },
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = "en-us"

# Storage is UTC and every timestamp the API emits is explicit UTC ISO-8601.
# The *display* timezone belongs to the frontend, not to the database.
TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = "static/"


# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}


# --------------------------------------------------------------------------- #
# Cache -- backs the refresh overlap lock
# --------------------------------------------------------------------------- #

REDIS_URL = env("REDIS_URL", "redis://127.0.0.1:6379")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": f"{REDIS_URL}/2",
    }
}


# --------------------------------------------------------------------------- #
# CORS -- the D3 frontend is served by Vite on a different origin in dev
# --------------------------------------------------------------------------- #

CORS_ALLOWED_ORIGINS = env_list(
    "DJANGO_CORS_ALLOWED_ORIGINS",
    ("http://localhost:5173", "http://127.0.0.1:5173"),
)

# Also allow any Vite dev port, so a second `npm run dev` (5174, 5175, ...) does
# not fail with an opaque CORS error. Development only -- in production the
# explicit list above is what applies.
if DEBUG:
    CORS_ALLOWED_ORIGIN_REGEXES = [r"^http://(localhost|127\.0\.0\.1):\d+$"]

CORS_ALLOW_CREDENTIALS = False


# --------------------------------------------------------------------------- #
# Django REST Framework
# --------------------------------------------------------------------------- #

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PAGINATION_CLASS": "leaderboard.api.pagination.LeaderboardPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "leaderboard.api.errors.leaderboard_exception_handler",
}


# --------------------------------------------------------------------------- #
# Celery -- broker, schedule and the twice-daily refresh
# --------------------------------------------------------------------------- #

CELERY_BROKER_URL = env("CELERY_BROKER_URL", f"{REDIS_URL}/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", f"{REDIS_URL}/1")

# NOTE: "China/Shanghai" is NOT a valid IANA zone -- `ZoneInfo` raises
# `ZoneInfoNotFoundError` and Celery beat refuses to start at all. The zone the
# schedule below is expressed in is Asia/Shanghai (UTC+8, no DST).
CELERY_TIMEZONE = env("CELERY_TIMEZONE", "Asia/Shanghai")
CELERY_ENABLE_UTC = True

CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60

CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

CELERY_BEAT_SCHEDULE = {
    # 08:00 and 20:00 Asia/Shanghai == 00:00 and 12:00 UTC.
    #
    # Only the orchestrator is scheduled. `refresh_all` runs LMArena and then
    # Artificial Analysis in-process, because AA's retention flag and its match
    # against the agent set both depend on agent entries that must already
    # exist; scheduling them independently would let AA read a stale agent set.
    "leaderboard-refresh-twice-daily": {
        "task": "leaderboard.refresh_all",
        "schedule": crontab(minute=0, hour="8,20"),
        "options": {
            # If beat was down and a run is picked up late, a stale one is worse
            # than a skipped one: the next run is only hours away.
            "expires": 3600,
        },
    },
}


# --------------------------------------------------------------------------- #
# Leaderboard ingestion
# --------------------------------------------------------------------------- #

#: Artificial Analysis API key. Left empty by default on purpose: a missing key
#: only fails the AA refresh -- the read-only API still serves whatever is
#: already stored, and `/metadata/` reports `configured: false`. Never commit a
#: real value; `backend/.env` is gitignored and `backend/.env.example` ships empty.
AA_API_KEY = env("AA_API_KEY", "")

AA_BASE_URL = env("AA_BASE_URL", "https://artificialanalysis.ai/api/v2")

#: Enables the harness-wrapper fold -- the one inferred join in the ladder. It
#: removes a single trailing evaluation-harness token (`codex-harness`) and
#: fires only on a unique, unshadowed candidate. Reasoning-effort tokens are
#: never folded; see `leaderboard/matching.py`.
LEADERBOARD_ENABLE_HARNESS_FOLD = env_bool("LEADERBOARD_ENABLE_HARNESS_FOLD", True)

#: How long a source may go unrefreshed before `/metadata/` reports it stale.
#: The schedule runs twice daily, so 14 hours tolerates one missed run.
LEADERBOARD_STALE_AFTER_SECONDS = env_int("LEADERBOARD_STALE_AFTER_SECONDS", 14 * 3600)

#: The LMArena dataset this project ingests. Overridable so a test or a pinned
#: deployment can point at a specific revision.
LEADERBOARD_LMARENA_DATASET = env(
    "LEADERBOARD_LMARENA_DATASET", "lmarena-ai/leaderboard-dataset"
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "leaderboard": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "leaderboard",
        },
    },
    "loggers": {
        "leaderboard": {
            "handlers": ["console"],
            "level": env("LEADERBOARD_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}
