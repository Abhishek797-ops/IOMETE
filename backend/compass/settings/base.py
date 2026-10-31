"""
Base settings for IOMETE COMPASS.

Environment-driven. Every variable referenced here is documented in `.env.example`.
Nothing in this file may contain a real credential or a production default.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

# backend/compass/settings/base.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BACKEND_DIR.parent

load_dotenv(REPO_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env")


def env(key: str, default: str | None = None) -> str | None:
    value = os.environ.get(key, default)
    return value.strip() if isinstance(value, str) else value


def env_bool(key: str, default: bool = False) -> bool:
    raw = env(key)
    if raw is None or raw == "":
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def env_int(key: str, default: int) -> int:
    raw = env(key)
    try:
        return int(raw) if raw else default
    except (TypeError, ValueError):
        return default


def env_list(key: str, default: list[str] | None = None) -> list[str]:
    raw = env(key)
    if not raw:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


# --------------------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------------------

SECRET_KEY = env("DJANGO_SECRET_KEY") or "insecure-dev-key-change-me-in-any-real-deployment"
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1", "0.0.0.0", "backend"])

# True when the deployment is running on synthetic seed data. Surfaced by the API so the
# frontend can show a demo-mode indicator. See `/api/v1/system/status/`.
COMPASS_DEMO_MODE = env_bool("COMPASS_DEMO_MODE", True)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    # third party
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    # local
    "common",
    "accounts",
    "organizations",
    "knowledge",
    "prospects",
    "lakehouse",
    "tickets",
    "playbooks",
    "aiengine",
    "integrations",
    "analytics",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "common.middleware.RequestContextMiddleware",
]

ROOT_URLCONF = "compass.urls"
WSGI_APPLICATION = "compass.wsgi.application"
ASGI_APPLICATION = "compass.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BACKEND_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

# --------------------------------------------------------------------------------------
# Database
#
# Defaults to SQLite so that `migrate && seed_demo && runserver` works on a clean machine
# with no infrastructure at all. Set DATABASE_URL to a Postgres DSN (docker compose does)
# to get the pgvector-accelerated retrieval path. See `aiengine/services/retrieval.py`.
# --------------------------------------------------------------------------------------


def _database_from_url(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme in {"postgres", "postgresql", "psql"}:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": (parsed.path or "/compass").lstrip("/"),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "localhost",
            "PORT": str(parsed.port or 5432),
            "CONN_MAX_AGE": env_int("DB_CONN_MAX_AGE", 60),
            "OPTIONS": {},
        }
    if parsed.scheme == "sqlite":
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": parsed.path or ":memory:"}
    raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme!r}")


_database_url = env("DATABASE_URL")
if _database_url:
    DATABASES = {"default": _database_from_url(_database_url)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BACKEND_DIR / "compass.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

# --------------------------------------------------------------------------------------
# Auth / passwords
# --------------------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Django's default is PBKDF2; keep it (no native deps) but raise the iteration floor.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

# --------------------------------------------------------------------------------------
# i18n / static / media
# --------------------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BACKEND_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT") or (BACKEND_DIR / "media"))

# Safe-upload policy, enforced in `tickets/services/attachments.py`.
UPLOAD_MAX_BYTES = env_int("UPLOAD_MAX_BYTES", 5 * 1024 * 1024)
UPLOAD_ALLOWED_EXTENSIONS = env_list(
    "UPLOAD_ALLOWED_EXTENSIONS", ["txt", "log", "json", "yaml", "yml", "csv", "png", "jpg", "jpeg"]
)
UPLOAD_ALLOWED_CONTENT_TYPES = env_list(
    "UPLOAD_ALLOWED_CONTENT_TYPES",
    [
        "text/plain", "text/csv", "application/json", "application/x-yaml",
        "text/yaml", "image/png", "image/jpeg",
    ],
)

# --------------------------------------------------------------------------------------
# DRF
# --------------------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("common.permissions.IsAuthenticatedAndActive",),
    "DEFAULT_PAGINATION_CLASS": "common.pagination.CompassPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "common.exceptions.compass_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ("rest_framework.throttling.ScopedRateThrottle",),
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON", "60/min"),
        "public": env("THROTTLE_PUBLIC", "30/min"),
        "ai": env("THROTTLE_AI", "20/min"),
        "auth": env("THROTTLE_AUTH", "10/min"),
    },
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "IOMETE COMPASS API",
    "DESCRIPTION": (
        "Customer enablement and FDE support-intelligence API for IOMETE COMPASS.\n\n"
        "All endpoints are versioned under `/api/v1/`. Tenant-scoped resources are filtered "
        "by the caller's organization memberships; cross-tenant access is only possible for "
        "approved, shared knowledge assets and anonymised aggregates.\n\n"
        "**Demo data notice.** Tickets, issue clusters and playbooks served by a seeded "
        "deployment are synthetic engineering scenarios, not IOMETE incident records."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": False,
    # Several apps define a `status` choice set. Without explicit names, generated
    # client enums get machine-suffixed names like `StatusAadEnum`, which are unusable.
    "ENUM_NAME_OVERRIDES": {
        "TicketStatusEnum": "tickets.models.TicketStatus.choices",
        "MembershipRoleEnum": "accounts.models.MembershipRole.choices",
        "SystemRoleEnum": "accounts.models.SystemRole.choices",
        "TicketComponentEnum": "tickets.models.TicketComponent.choices",
        "FailureCategoryEnum": "tickets.models.FailureCategory.choices",
        "SeverityEnum": "tickets.models.Severity.choices",
        "EnvironmentEnum": "tickets.models.Environment.choices",
        "ClusterStatusEnum": "tickets.models.ClusterStatus.choices",
        "GateStatusEnum": "tickets.models.GateStatus.choices",
        "ApprovalStatusEnum": "playbooks.models.ApprovalStatus.choices",
        "ExecutionStatusEnum": "playbooks.models.ExecutionStatus.choices",
        "RiskLevelEnum": "playbooks.models.RiskLevel.choices",
        "StepTypeEnum": "playbooks.models.StepType.choices",
        "ResponseKindEnum": "playbooks.models.ResponseKind.choices",
        "ApprovalDecisionEnum": "playbooks.models.ApprovalDecision.choices",
        "IntegrationProviderEnum": "integrations.models.IntegrationProvider.choices",
        "IntegrationModeEnum": "integrations.models.IntegrationMode.choices",
        "SyncStatusEnum": "integrations.models.SyncStatus.choices",
        "PlaygroundModeEnum": "lakehouse.models.PlaygroundMode.choices",
        "DemoRequestStatusEnum": "prospects.models.DemoRequestStatus.choices",
        "FitBandEnum": "prospects.models.FitBand.choices",
        "UseCaseEnum": "prospects.models.UseCase.choices",
        "CompanyTypeEnum": "prospects.models.CompanyType.choices",
        "DataVolumeEnum": "prospects.models.DataVolume.choices",
        "InfrastructureLocationEnum": "prospects.models.InfrastructureLocation.choices",
        "SovereigntyRequirementEnum": "prospects.models.SovereigntyRequirement.choices",
        "CurrentArchitectureEnum": "prospects.models.CurrentArchitecture.choices",
        "DeploymentModelEnum": "accounts.models.DeploymentModel.choices",
        "CloudProviderEnum": "accounts.models.CloudProvider.choices",
        "SupportTierEnum": "accounts.models.SupportTier.choices",
        "TicketEventTypeEnum": "tickets.models.TicketEventType.choices",
    },
    "TAGS": [
        {"name": "auth", "description": "Authentication and the current user."},
        {"name": "organizations", "description": "Tenant management."},
        {"name": "knowledge", "description": "Source-backed IOMETE product knowledge."},
        {"name": "prospects", "description": "Fit assessments, architecture recommendations, demo requests."},
        {"name": "lakehouse", "description": "Lakehouse playground: datasets, schemas, sample SQL."},
        {"name": "tickets", "description": "Support tickets, similarity search and issue clusters."},
        {"name": "playbooks", "description": "Resolution playbooks and Resolution Replay executions."},
        {"name": "fde", "description": "FDE command center: inbox, review queue, knowledge drafts."},
        {"name": "analytics", "description": "Support-effectiveness analytics."},
        {"name": "integrations", "description": "Jira and IOMETE connector configuration."},
        {"name": "system", "description": "Runtime capability and demo-mode reporting."},
    ],
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": __import__("datetime").timedelta(
        minutes=env_int("JWT_ACCESS_MINUTES", 60)
    ),
    "REFRESH_TOKEN_LIFETIME": __import__("datetime").timedelta(
        days=env_int("JWT_REFRESH_DAYS", 7)
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": env("JWT_SIGNING_KEY") or SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# --------------------------------------------------------------------------------------
# CORS / CSRF
# --------------------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS", ["http://localhost:3000", "http://127.0.0.1:3000"]
)
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", CORS_ALLOWED_ORIGINS)

# --------------------------------------------------------------------------------------
# Encryption of integration credentials at rest (common/crypto.py)
# --------------------------------------------------------------------------------------

COMPASS_ENCRYPTION_KEY = env("COMPASS_ENCRYPTION_KEY")

# --------------------------------------------------------------------------------------
# AI configuration
# --------------------------------------------------------------------------------------

# "demo" => deterministic, offline, reproducible. "gemini" => live Gemini via google-genai.
LLM_PROVIDER = (env("LLM_PROVIDER", "demo") or "demo").lower()
LLM_MODEL = env("LLM_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY = env("GEMINI_API_KEY")

EMBEDDING_PROVIDER = (env("EMBEDDING_PROVIDER", "hashing") or "hashing").lower()
EMBEDDING_MODEL = env("EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_DIM = env_int("EMBEDDING_DIM", 384)

# pgvector is used only when the DB is Postgres AND this is on AND the extension installs.
# `HybridRetrievalService` reports which backend actually answered.
USE_PGVECTOR = env_bool("USE_PGVECTOR", True)

RETRIEVAL_WEIGHTS = {
    "vector": float(env("RETRIEVAL_W_VECTOR", "1.0")),
    "lexical": float(env("RETRIEVAL_W_LEXICAL", "0.9")),
    "fingerprint": float(env("RETRIEVAL_W_FINGERPRINT", "1.4")),
    "metadata": float(env("RETRIEVAL_W_METADATA", "0.6")),
}
RETRIEVAL_RRF_K = env_int("RETRIEVAL_RRF_K", 60)
RETRIEVAL_CANDIDATE_LIMIT = env_int("RETRIEVAL_CANDIDATE_LIMIT", 50)

# --------------------------------------------------------------------------------------
# Integrations
# --------------------------------------------------------------------------------------

JIRA_BASE_URL = env("JIRA_BASE_URL")
JIRA_EMAIL = env("JIRA_EMAIL")
JIRA_API_TOKEN = env("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = env("JIRA_PROJECT_KEY")
JIRA_WEBHOOK_SECRET = env("JIRA_WEBHOOK_SECRET")

# Connected mode for the lakehouse playground requires ALL of these plus a successful
# handshake. There is deliberately no code path that reports "connected" without one.
IOMETE_BASE_URL = env("IOMETE_BASE_URL")
IOMETE_API_TOKEN = env("IOMETE_API_TOKEN")
IOMETE_WORKSPACE = env("IOMETE_WORKSPACE")
IOMETE_VERIFY_TLS = env_bool("IOMETE_VERIFY_TLS", True)
INTEGRATION_HTTP_TIMEOUT = env_int("INTEGRATION_HTTP_TIMEOUT", 10)

# --------------------------------------------------------------------------------------
# Celery (optional — the product is fully functional without it)
# --------------------------------------------------------------------------------------

CELERY_ENABLED = env_bool("CELERY_ENABLED", False)
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = not CELERY_ENABLED

# --------------------------------------------------------------------------------------
# Product knowledge base
# --------------------------------------------------------------------------------------

PRODUCT_KNOWLEDGE_PATH = Path(
    env("PRODUCT_KNOWLEDGE_PATH") or (REPO_ROOT / "docs" / "product-knowledge" / "knowledge.json")
)

# --------------------------------------------------------------------------------------
# Logging — with a redaction filter so a stray log call cannot leak a credential.
# --------------------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact": {"()": "common.logging_filters.RedactingFilter"},
    },
    "formatters": {
        "standard": {"format": "[{levelname}] {asctime} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "filters": ["redact"],
        },
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "compass": {"level": env("LOG_LEVEL", "INFO"), "handlers": ["console"], "propagate": False},
    },
}
