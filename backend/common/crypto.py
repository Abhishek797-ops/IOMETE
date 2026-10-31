"""
Encryption for integration credentials at rest.

Threat being addressed: a Jira API token or an IOMETE bearer token sitting in plaintext in
the `integrations_integrationconfiguration` table is readable by anyone with a database
dump, a read replica, or a backup file. Encrypting at the field level means a DB-level
compromise does not immediately yield working credentials for a customer's Jira or
lakehouse.

The key comes from `COMPASS_ENCRYPTION_KEY`. In production its absence is a hard error
(see `compass/settings/prod.py`). In development, a key is derived from `SECRET_KEY` so the
feature works out of the box without silently storing plaintext.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models

logger = logging.getLogger("compass.crypto")

_PREFIX = "enc:v1:"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = getattr(settings, "COMPASS_ENCRYPTION_KEY", None)
    if key:
        try:
            return Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "COMPASS_ENCRYPTION_KEY is not a valid Fernet key. Generate one with: "
                "python -c 'from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())'"
            ) from exc
    # Development fallback: deterministic key derived from SECRET_KEY. Never used in
    # production, where prod.py raises if COMPASS_ENCRYPTION_KEY is unset.
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_text(plaintext: str) -> str:
    if plaintext == "" or plaintext is None:
        return ""
    return _PREFIX + _fernet().encrypt(plaintext.encode()).decode()


def decrypt_text(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    if not ciphertext.startswith(_PREFIX):
        # Value predates encryption (or was written directly by a fixture). Return it
        # as-is so the application keeps working, but make the gap visible.
        logger.warning("Encountered an unencrypted credential value; re-save to encrypt it.")
        return ciphertext
    try:
        return _fernet().decrypt(ciphertext[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        # Wrong or rotated key. Returning "" degrades the integration to demo mode rather
        # than crashing the request — and the integration will correctly report that it is
        # not connected.
        logger.error("Could not decrypt a credential: COMPASS_ENCRYPTION_KEY may have rotated.")
        return ""


class EncryptedJSONField(models.TextField):
    """
    A JSON dict stored Fernet-encrypted.

    Used for `IntegrationConfiguration.credentials`. The API never serializes this field
    back out — see `integrations/serializers.py`, which exposes only which keys are
    present, never their values.
    """

    description = "A JSON object encrypted at rest"

    def from_db_value(self, value, expression, connection) -> dict[str, Any]:
        if value is None:
            return {}
        raw = decrypt_text(value)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Decrypted credential payload was not valid JSON; treating as empty.")
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def to_python(self, value) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value is None or value == "":
            return {}
        raw = decrypt_text(value) if str(value).startswith(_PREFIX) else str(value)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def get_prep_value(self, value) -> str:
        if value in (None, "", {}):
            return encrypt_text(json.dumps({}))
        if isinstance(value, str) and value.startswith(_PREFIX):
            return value
        if not isinstance(value, dict):
            raise ValueError("EncryptedJSONField expects a dict.")
        return encrypt_text(json.dumps(value, separators=(",", ":"), sort_keys=True))

    def value_to_string(self, obj) -> str:
        # Deliberately refuses to serialize into a fixture/dumpdata payload. Exporting
        # encrypted credentials into a plaintext JSON file defeats the purpose.
        return encrypt_text(json.dumps({}))
