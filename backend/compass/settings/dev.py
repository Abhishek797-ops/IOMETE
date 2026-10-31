"""Development settings. Loud errors, permissive CORS for localhost, browsable API."""

from .base import *
from .base import REST_FRAMEWORK, env_bool

DEBUG = env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = ["*"]

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ),
}

# Emails to the console so the demo-request funnel is observable without an SMTP server.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
