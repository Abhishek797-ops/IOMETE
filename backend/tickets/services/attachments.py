"""
Safe attachment handling.

Customers attach logs and screenshots to tickets. Every one of those is a file of unknown
provenance being written to our disk and later served back, so the controls here are:

1. **Extension *and* declared content-type must both be on the allowlist**, and must agree
   with each other. A `.log` claiming to be `text/html` is rejected rather than normalised.
2. **Size cap** before anything is read into memory.
3. **Generated storage name.** The client-supplied filename is kept as metadata only. Using
   it as a path is how `../../etc/passwd` and `shell.php` end up on disk.
4. **Text uploads are redacted in place.** A pasted log is the most likely place for a
   credential to arrive, so text files are rewritten with secrets removed before the bytes
   are stored. The original is never written.
5. **Served only through an authorizing view.** `TicketAttachment.download_url` points at a
   view that re-checks tenancy; media is never exposed as a guessable static path.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction

from accounts.models import User
from aiengine.services import redaction
from common.audit import record_audit
from common.exceptions import DomainValidationError

from ..models import Ticket, TicketAttachment, TicketEvent, TicketEventType

logger = logging.getLogger("compass.attachments")

#: Extensions whose contents we rewrite with redaction applied.
TEXT_EXTENSIONS = {"txt", "log", "json", "yaml", "yml", "csv"}

#: Extension → acceptable declared content types. Both must match.
_EXTENSION_TYPES = {
    "txt": {"text/plain"},
    "log": {"text/plain", "application/octet-stream"},
    "json": {"application/json", "text/plain"},
    "yaml": {"application/x-yaml", "text/yaml", "text/plain"},
    "yml": {"application/x-yaml", "text/yaml", "text/plain"},
    "csv": {"text/csv", "text/plain"},
    "png": {"image/png"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
}

#: Leading bytes that must match for image uploads. Stops an executable renamed to .png.
_MAGIC = {
    "png": b"\x89PNG\r\n\x1a\n",
    "jpg": b"\xff\xd8\xff",
    "jpeg": b"\xff\xd8\xff",
}


def _extension(name: str) -> str:
    return os.path.splitext(name or "")[1].lstrip(".").lower()


@transaction.atomic
def upload(
    *, ticket: Ticket, uploaded_file, user: User, is_internal: bool = False
) -> TicketAttachment:
    original_name = os.path.basename(uploaded_file.name or "attachment")
    extension = _extension(original_name)
    declared_type = (getattr(uploaded_file, "content_type", "") or "").split(";")[0].strip()
    size = uploaded_file.size or 0

    if is_internal and not user.is_iomete_staff:
        raise DomainValidationError(
            detail="Only IOMETE staff can mark an attachment internal."
        )

    if size > settings.UPLOAD_MAX_BYTES:
        raise DomainValidationError(
            detail=f"That file is {size / 1_048_576:.1f} MB. The limit is "
            f"{settings.UPLOAD_MAX_BYTES / 1_048_576:.0f} MB. For large logs, attach the "
            "relevant excerpt instead — it also produces better matches."
        )
    if size == 0:
        raise DomainValidationError(detail="That file is empty.")

    if extension not in settings.UPLOAD_ALLOWED_EXTENSIONS:
        raise DomainValidationError(
            detail=f"`.{extension or '?'}` files are not accepted. Allowed: "
            + ", ".join(f".{ext}" for ext in settings.UPLOAD_ALLOWED_EXTENSIONS)
        )
    if declared_type and declared_type not in settings.UPLOAD_ALLOWED_CONTENT_TYPES:
        raise DomainValidationError(
            detail=f"Content type {declared_type!r} is not accepted."
        )
    expected_types = _EXTENSION_TYPES.get(extension, set())
    if declared_type and expected_types and declared_type not in expected_types:
        raise DomainValidationError(
            detail=f"A `.{extension}` file should not be {declared_type!r}. The extension "
            "and content type disagree, so the upload was rejected."
        )

    raw = uploaded_file.read()

    if magic := _MAGIC.get(extension):
        if not raw.startswith(magic):
            raise DomainValidationError(
                detail=f"That file does not contain {extension.upper()} data despite its "
                "extension."
            )

    redaction_summary: dict[str, int] = {}
    redaction_applied = False
    if extension in TEXT_EXTENSIONS:
        try:
            decoded = raw.decode("utf-8", errors="replace")
        except Exception as exc:  # pragma: no cover
            raise DomainValidationError(detail="That text file could not be read.") from exc
        result = redaction.redact(decoded)
        redaction_summary = result.summary
        redaction_applied = result.was_redacted
        # The redacted bytes replace the originals. We never write the original to disk.
        raw = result.text.encode("utf-8")

    checksum = hashlib.sha256(raw).hexdigest()
    # Generated name: the client's filename never becomes a path component.
    storage_name = f"{uuid.uuid4().hex}.{extension}"

    attachment = TicketAttachment(
        ticket=ticket,
        original_name=original_name[:255],
        content_type=declared_type or "application/octet-stream",
        size_bytes=len(raw),
        checksum_sha256=checksum,
        uploaded_by=user,
        redaction_applied=redaction_applied,
        redaction_summary=redaction_summary,
        is_internal=is_internal,
    )
    attachment.file.save(storage_name, ContentFile(raw), save=False)
    attachment.save()

    TicketEvent.objects.create(
        ticket=ticket,
        event_type=TicketEventType.ATTACHMENT,
        author=user,
        author_label=user.email,
        body=(
            f"Attached {original_name}"
            + (
                f" — {sum(redaction_summary.values())} sensitive value(s) redacted before "
                "storage."
                if redaction_applied
                else "."
            )
        ),
        is_internal=is_internal,
        metadata={"size_bytes": len(raw), "redactions": redaction_summary},
    )
    record_audit(
        action="ticket.attachment_added",
        actor=user,
        organization=ticket.organization,
        target_type="ticket_attachment",
        target_id=str(attachment.id),
        summary=f"{ticket.reference}: attached {original_name[:120]}",
        metadata={
            "size_bytes": len(raw),
            "redaction_applied": redaction_applied,
            "is_internal": is_internal,
        },
    )
    return attachment
