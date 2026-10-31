"""
Identity and tenancy models.

Two distinct notions of role, deliberately kept apart:

* ``User.system_role`` — which *side* the person is on. A customer, or IOMETE's own staff
  (FDE, FDE lead, platform admin). This decides cross-tenant visibility.
* ``Membership.role`` — what the person may do *inside one customer organization*
  (viewer, engineer, admin). This decides, for example, whether they can approve a change
  step on their own cluster.

Collapsing these into one field is tempting and wrong: an FDE is not "an admin of every
organization", and a customer admin is not a junior FDE.
"""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from common.models import BaseModel


class SystemRole(models.TextChoices):
    CUSTOMER = "customer", "Customer"
    FDE = "fde", "Forward Deployed Engineer"
    FDE_LEAD = "fde_lead", "FDE Lead"
    PLATFORM_ADMIN = "platform_admin", "Platform Administrator"


IOMETE_STAFF_ROLES = frozenset(
    {SystemRole.FDE.value, SystemRole.FDE_LEAD.value, SystemRole.PLATFORM_ADMIN.value}
)


class MembershipRole(models.TextChoices):
    VIEWER = "viewer", "Viewer"
    ENGINEER = "engineer", "Engineer"
    ADMIN = "admin", "Organization Administrator"


# Ordered weakest → strongest, so `has_membership_role("engineer")` is satisfied by an admin.
_MEMBERSHIP_RANK = {
    MembershipRole.VIEWER.value: 1,
    MembershipRole.ENGINEER.value: 2,
    MembershipRole.ADMIN.value: 3,
}


class DeploymentModel(models.TextChoices):
    ON_PREMISES = "on_premises", "On-premises"
    PRIVATE_CLOUD = "private_cloud", "Private cloud"
    PUBLIC_CLOUD = "public_cloud", "Public cloud"
    HYBRID = "hybrid", "Hybrid"


class CloudProvider(models.TextChoices):
    AWS = "aws", "AWS"
    AZURE = "azure", "Azure"
    GCP = "gcp", "Google Cloud"
    ON_PREM = "on_prem", "On-premises / bare metal"
    OTHER = "other", "Other"
    NONE = "none", "Not applicable"


class SupportTier(models.TextChoices):
    STANDARD = "standard", "Standard"
    ENTERPRISE = "enterprise", "Enterprise"
    STRATEGIC = "strategic", "Strategic (dedicated FDE)"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email: str, password: str | None, **extra):
        if not email:
            raise ValueError("A user must have an email address.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra):
        extra.setdefault("system_role", SystemRole.CUSTOMER)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra):
        extra.setdefault("system_role", SystemRole.PLATFORM_ADMIN)
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._create(email, password, **extra)


class User(BaseModel, AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True, db_index=True)
    full_name = models.CharField(max_length=200)
    job_title = models.CharField(max_length=150, blank=True)
    system_role = models.CharField(
        max_length=32,
        choices=SystemRole.choices,
        default=SystemRole.CUSTOMER,
        db_index=True,
        help_text="Which side of the relationship this user is on. Controls cross-tenant visibility.",
    )
    avatar_initials = models.CharField(max_length=3, blank=True)
    timezone_name = models.CharField(max_length=64, default="UTC")

    is_active = models.BooleanField(default=True, db_index=True)
    is_staff = models.BooleanField(
        default=False, help_text="Access to the Django admin site. Distinct from system_role."
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)
    is_synthetic = models.BooleanField(default=False, db_index=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ("full_name",)
        indexes = [models.Index(fields=["system_role", "is_active"])]

    def __str__(self) -> str:
        return f"{self.full_name} <{self.email}>"

    def save(self, *args, **kwargs):
        self.email = self.email.lower().strip()
        if not self.avatar_initials and self.full_name:
            parts = [p for p in self.full_name.split() if p]
            self.avatar_initials = (
                (parts[0][0] + parts[-1][0]).upper() if len(parts) > 1 else parts[0][:2].upper()
            )
        super().save(*args, **kwargs)

    # --- Role helpers -----------------------------------------------------------------

    @property
    def is_iomete_staff(self) -> bool:
        """
        True for FDE, FDE lead and platform admin.

        Read by `TenantQuerySet.for_user()` to decide cross-tenant visibility, so this
        property is a security-relevant surface: do not widen it casually.
        """
        return self.system_role in IOMETE_STAFF_ROLES

    @property
    def is_customer(self) -> bool:
        return self.system_role == SystemRole.CUSTOMER

    def organization_ids(self) -> list:
        """Ids of organizations this user is an active member of. Cached per instance."""
        if not hasattr(self, "_organization_ids_cache"):
            self._organization_ids_cache = list(
                self.memberships.filter(is_active=True).values_list("organization_id", flat=True)
            )
        return self._organization_ids_cache

    def has_membership_role(self, minimum: str, organization_id=None) -> bool:
        """
        Does this user hold at least `minimum` in (optionally) a specific organization?

        Rank-based, so an `admin` satisfies a check for `engineer`. IOMETE staff are not
        granted membership roles implicitly — endpoints that staff should reach use
        `IsIometeStaff` explicitly, which keeps the two role systems from bleeding together.
        """
        required = _MEMBERSHIP_RANK.get(minimum)
        if required is None:
            raise ValueError(f"Unknown membership role {minimum!r}")
        memberships = self.memberships.filter(is_active=True)
        if organization_id is not None:
            memberships = memberships.filter(organization_id=organization_id)
        return any(
            _MEMBERSHIP_RANK.get(role, 0) >= required
            for role in memberships.values_list("role", flat=True)
        )

    @property
    def primary_organization(self):
        membership = (
            self.memberships.filter(is_active=True)
            .select_related("organization")
            .order_by("-is_default", "created_at")
            .first()
        )
        return membership.organization if membership else None

    def touch_last_seen(self) -> None:
        self.last_seen_at = timezone.now()
        self.save(update_fields=["last_seen_at", "updated_at"])


class Organization(BaseModel):
    """
    A customer tenant.

    The infrastructure fields (`iomete_version`, `deployment_model`, `cloud_provider`,
    `environment_label`) are not decoration: they are the metadata the retrieval
    compatibility gate uses to decide whether a historical resolution from another
    customer is applicable here.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120, unique=True, db_index=True)
    industry = models.CharField(max_length=120, blank=True)
    region = models.CharField(max_length=120, blank=True)
    employee_band = models.CharField(max_length=60, blank=True)

    deployment_model = models.CharField(
        max_length=32, choices=DeploymentModel.choices, default=DeploymentModel.PUBLIC_CLOUD
    )
    cloud_provider = models.CharField(
        max_length=32, choices=CloudProvider.choices, default=CloudProvider.AWS
    )
    iomete_version = models.CharField(
        max_length=32,
        blank=True,
        help_text="e.g. 3.19.1. Used by the retrieval compatibility gate.",
    )
    environment_label = models.CharField(
        max_length=64,
        blank=True,
        help_text="Free-text environment descriptor, e.g. 'production', 'staging'.",
    )
    kubernetes_distribution = models.CharField(max_length=80, blank=True)
    object_storage = models.CharField(max_length=80, blank=True)

    support_tier = models.CharField(
        max_length=32, choices=SupportTier.choices, default=SupportTier.STANDARD
    )
    assigned_fde = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_organizations",
        help_text="Primary FDE relationship. Advisory: it does not grant or restrict access.",
    )
    data_residency_requirement = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)

    is_active = models.BooleanField(default=True, db_index=True)
    is_synthetic = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    @property
    def member_count(self) -> int:
        return self.memberships.filter(is_active=True).count()


class Membership(BaseModel):
    """A user's role within one organization."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(
        max_length=32, choices=MembershipRole.choices, default=MembershipRole.VIEWER, db_index=True
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    invited_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="sent_invitations"
    )

    class Meta:
        ordering = ("organization__name", "user__full_name")
        constraints = [
            models.UniqueConstraint(fields=["user", "organization"], name="unique_user_org"),
        ]
        indexes = [models.Index(fields=["organization", "role", "is_active"])]

    def __str__(self) -> str:
        return f"{self.user.email} @ {self.organization.slug} ({self.role})"


class AuditLog(BaseModel):
    """
    Append-only record of security- and workflow-relevant actions.

    `actor` is SET_NULL on user deletion, which is why `actor_label` exists — the trail must
    survive the account. There is no update or delete path for these rows in the API.
    """

    action = models.CharField(max_length=80, db_index=True)
    actor = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_entries"
    )
    actor_label = models.CharField(
        max_length=255, blank=True, help_text="Durable textual identity of the actor."
    )
    organization = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
        db_index=True,
    )
    target_type = models.CharField(max_length=100, blank=True, db_index=True)
    target_id = models.CharField(max_length=100, blank=True, db_index=True)
    summary = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    request_id = models.CharField(max_length=64, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["target_type", "target_id"]),
        ]
        verbose_name = "audit log entry"
        verbose_name_plural = "audit log"

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} by {self.actor_label}"
