"""
Test settings.

Pinned to the deterministic demo AI providers and a fast password hasher so the suite is
reproducible and does not make a network call. Retrieval-quality tests depend on the
hashing embedder being deterministic.
"""

from .base import *

DEBUG = False
ALLOWED_HOSTS = ["*", "testserver"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

LLM_PROVIDER = "demo"
EMBEDDING_PROVIDER = "hashing"
EMBEDDING_DIM = 384

# No external integration may be reachable from the test suite.
JIRA_BASE_URL = None
JIRA_EMAIL = None
JIRA_API_TOKEN = None
IOMETE_BASE_URL = None
IOMETE_API_TOKEN = None

CELERY_ENABLED = False
CELERY_TASK_ALWAYS_EAGER = True

COMPASS_DEMO_MODE = True

# Fixed key so encrypted-field round-trip tests are stable.
COMPASS_ENCRYPTION_KEY = "L1aT6tRBYV7Sg5fGxJ1cTt7g2WqY9d1v4Kk8H3nQ0pA="

# Throttling off: it makes tests flaky and is covered by its own dedicated test.
REST_FRAMEWORK = {**globals()["REST_FRAMEWORK"], "DEFAULT_THROTTLE_CLASSES": ()}

LOGGING["root"]["level"] = "ERROR"
