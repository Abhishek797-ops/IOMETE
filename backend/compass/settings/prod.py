"""
Production settings.

Deliberately strict: this module raises at import time if a required secret is missing,
rather than silently booting with an insecure default.
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *
from .base import COMPASS_ENCRYPTION_KEY, SECRET_KEY, env, env_bool, env_int, env_list

DEBUG = False

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", [])

_INSECURE_KEY = "insecure-dev-key-change-me-in-any-real-deployment"
if not SECRET_KEY or SECRET_KEY == _INSECURE_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set to a unique value in production.")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be set in production.")
if not env("DATABASE_URL"):
    raise ImproperlyConfigured("DATABASE_URL must be set in production (Postgres expected).")
if not COMPASS_ENCRYPTION_KEY:
    raise ImproperlyConfigured(
        "COMPASS_ENCRYPTION_KEY must be set in production so integration credentials are "
        "encrypted at rest. Generate one with: "
        "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
    )

# --- Transport security -------------------------------------------------------------
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False
X_FRAME_OPTIONS = "DENY"

# Browsable API off: it is a needless attack surface on a production API.
REST_FRAMEWORK = {
    **globals()["REST_FRAMEWORK"],
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
}
