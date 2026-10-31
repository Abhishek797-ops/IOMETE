"""
Shared model primitives.

`TenantOwnedModel` + `TenantQuerySet.for_user()` are the *only* sanctioned mechanism for
tenant scoping in this codebase. Hand-filtering `organization=` in a view is a security
bug waiting to happen: it is easy to forget on one of six endpoints, and the omission is
invisible in review. Centralising it means a single place to audit and a single place to test.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from django.db import models

if TYPE_CHECKING:  # pragma: no cover
    from accounts.models import User


class BaseModel(models.Model):
    """UUID primary key plus creation/update stamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ("-created_at",)


class TenantQuerySet(models.QuerySet):
    """A queryset that knows how to narrow itself to what a user may legitimately see."""

    def for_user(self, user: User | None):
        """
        Scope this queryset to `user`.

        - Unauthenticated or deactivated users see nothing.
        - IOMETE-side staff (``platform_admin``, ``fde_lead``, ``fde``) see every tenant's
          rows. They are the vendor's own support engineers; cross-customer visibility is
          the entire point of the FDE command center. Customer-private *fields* (internal
          notes, raw diagnostics) are still controlled separately at the serializer layer.
        - A customer user sees only rows belonging to organizations they are an active
          member of.
        """
        if user is None or not getattr(user, "is_authenticated", False):
            return self.none()
        if not getattr(user, "is_active", False):
            return self.none()
        if getattr(user, "is_iomete_staff", False):
            return self
        org_ids = user.organization_ids()
        if not org_ids:
            return self.none()
        return self.filter(organization_id__in=org_ids)

    def for_organization(self, organization) -> TenantQuerySet:
        return self.filter(organization=organization)


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):  # type: ignore[misc]
    """Default manager for tenant-owned models."""

    use_in_migrations = False


class TenantOwnedModel(BaseModel):
    """
    A row that belongs to exactly one customer organization.

    The `organization` FK is non-null by design: a tenant-owned row with no tenant is an
    unreachable, unauditable orphan.
    """

    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
        db_index=True,
    )

    objects = TenantManager()

    class Meta:
        abstract = True
        ordering = ("-created_at",)


class SyntheticDataMixin(models.Model):
    """
    Marks a row as synthetic demo data.

    COMPASS ships seeded tickets, clusters and playbooks so the product is demonstrable
    without a real support history. Those rows must never be mistaken for real IOMETE
    incident records, so the flag travels with the data into the API and into the UI
    rather than living only in a README.
    """

    is_synthetic = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True for seeded demo data. Surfaced in the API and labelled in the UI.",
    )

    class Meta:
        abstract = True
