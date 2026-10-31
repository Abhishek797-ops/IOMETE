"""
Identity service.

Holds the authentication and user/membership rules so the views stay thin. Every mutation
here writes an audit row inside the same transaction as the change.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from common.audit import record_audit
from common.exceptions import ConflictError, DomainValidationError

from ..models import Membership, MembershipRole, Organization, SystemRole, User


@dataclass(frozen=True)
class TokenPair:
    access: str
    refresh: str
    user: User


def login(*, email: str, password: str) -> TokenPair:
    """
    Authenticate and issue a JWT pair.

    A failed attempt is audited (without the password, obviously) because repeated
    failures against one account are the signal an audit log exists to surface.
    """
    normalized = (email or "").strip().lower()
    user = authenticate(username=normalized, password=password)

    if user is None:
        # Classify the failure for the *audit trail only*. Django's ModelBackend already
        # refuses an inactive account, so this is the only place the distinction between
        # "no such account", "deactivated" and "wrong password" can be recorded — and it is
        # genuinely useful to an operator reading the log.
        #
        # The *response* is one generic message in every case. Telling the caller which of
        # the three it was turns this endpoint into an account-enumeration oracle, and
        # "this account is deactivated" additionally confirms that the address is real.
        existing = User.objects.filter(email=normalized).first()
        if existing is None:
            reason = "no such account"
        elif not existing.is_active:
            reason = "account is deactivated"
        else:
            reason = "incorrect password"

        record_audit(
            action="user.login_failed",
            actor=existing if existing and existing.is_active else None,
            summary=f"Failed login for {normalized or '(blank)'}: {reason}",
            metadata={"email": normalized, "reason": reason},
        )
        raise DomainValidationError(detail="Incorrect email address or password.")

    refresh = RefreshToken.for_user(user)
    user.last_seen_at = timezone.now()
    user.save(update_fields=["last_seen_at", "updated_at"])

    record_audit(
        action="user.login",
        actor=user,
        organization=user.primary_organization,
        summary=f"{user.email} signed in",
        metadata={"system_role": user.system_role},
    )
    return TokenPair(access=str(refresh.access_token), refresh=str(refresh), user=user)


def logout(*, user: User, refresh_token: str) -> None:
    """Blacklist a refresh token. Tolerant of an already-invalid token."""
    try:
        RefreshToken(refresh_token).blacklist()
    except Exception as exc:
        raise DomainValidationError(
            detail="That refresh token is not valid, so there was nothing to revoke."
        ) from exc
    record_audit(action="user.logout", actor=user, summary=f"{user.email} signed out")


@transaction.atomic
def create_user(
    *,
    actor: User,
    email: str,
    full_name: str,
    system_role: str = SystemRole.CUSTOMER,
    job_title: str = "",
    password: str | None = None,
    is_active: bool = True,
) -> User:
    if User.objects.filter(email=email.strip().lower()).exists():
        raise ConflictError(detail="A user with that email address already exists.")
    user = User.objects.create_user(
        email=email,
        password=password,
        full_name=full_name,
        job_title=job_title,
        system_role=system_role,
        is_active=is_active,
    )
    record_audit(
        action="user.created",
        actor=actor,
        target_type="user",
        target_id=str(user.id),
        summary=f"Created {user.email} with role {user.system_role}",
        metadata={"system_role": user.system_role},
    )
    return user


@transaction.atomic
def change_system_role(*, actor: User, user: User, new_role: str) -> User:
    """
    Change a user's system role.

    Guards against two foot-guns: self-demotion, and removing the last platform admin —
    either of which locks everyone out of user management.
    """
    if new_role not in dict(SystemRole.choices):
        raise DomainValidationError(detail="Unknown system role.")
    if user.system_role == new_role:
        return user

    if actor.pk == user.pk and new_role != SystemRole.PLATFORM_ADMIN:
        raise DomainValidationError(
            detail="You cannot remove your own platform-administrator role. Ask another "
            "administrator to do it."
        )
    if user.system_role == SystemRole.PLATFORM_ADMIN:
        remaining = (
            User.objects.filter(system_role=SystemRole.PLATFORM_ADMIN, is_active=True)
            .exclude(pk=user.pk)
            .count()
        )
        if remaining == 0:
            raise ConflictError(
                detail="This is the last active platform administrator. Promote another user "
                "first, or the deployment will have no one who can manage users."
            )

    previous = user.system_role
    user.system_role = new_role
    user.save(update_fields=["system_role", "updated_at"])
    record_audit(
        action="user.role_changed",
        actor=actor,
        target_type="user",
        target_id=str(user.id),
        summary=f"{user.email}: {previous} → {new_role}",
        metadata={"from": previous, "to": new_role},
    )
    return user


@transaction.atomic
def deactivate_user(*, actor: User, user: User) -> User:
    if actor.pk == user.pk:
        raise DomainValidationError(detail="You cannot deactivate your own account.")
    if user.system_role == SystemRole.PLATFORM_ADMIN:
        remaining = (
            User.objects.filter(system_role=SystemRole.PLATFORM_ADMIN, is_active=True)
            .exclude(pk=user.pk)
            .count()
        )
        if remaining == 0:
            raise ConflictError(detail="Cannot deactivate the last active platform administrator.")
    user.is_active = False
    user.save(update_fields=["is_active", "updated_at"])
    record_audit(
        action="user.deactivated",
        actor=actor,
        target_type="user",
        target_id=str(user.id),
        summary=f"Deactivated {user.email}",
    )
    return user


@transaction.atomic
def add_membership(
    *, actor: User, user: User, organization: Organization, role: str = MembershipRole.VIEWER
) -> Membership:
    if role not in dict(MembershipRole.choices):
        raise DomainValidationError(detail="Unknown membership role.")
    if Membership.objects.filter(user=user, organization=organization).exists():
        raise ConflictError(detail="That user is already a member of this organization.")

    membership = Membership.objects.create(
        user=user,
        organization=organization,
        role=role,
        invited_by=actor if getattr(actor, "pk", None) else None,
        is_default=not Membership.objects.filter(user=user, is_active=True).exists(),
    )
    record_audit(
        action="membership.created",
        actor=actor,
        organization=organization,
        target_type="membership",
        target_id=str(membership.id),
        summary=f"Added {user.email} to {organization.name} as {role}",
        metadata={"role": role},
    )
    return membership


@transaction.atomic
def change_membership_role(*, actor: User, membership: Membership, new_role: str) -> Membership:
    if new_role not in dict(MembershipRole.choices):
        raise DomainValidationError(detail="Unknown membership role.")
    if membership.role == new_role:
        return membership

    # Do not let an organization lose its last admin.
    if membership.role == MembershipRole.ADMIN and new_role != MembershipRole.ADMIN:
        remaining = (
            Membership.objects.filter(
                organization=membership.organization, role=MembershipRole.ADMIN, is_active=True
            )
            .exclude(pk=membership.pk)
            .count()
        )
        if remaining == 0:
            raise ConflictError(
                detail=f"{membership.organization.name} would be left with no administrator. "
                "Promote another member first."
            )

    previous = membership.role
    membership.role = new_role
    membership.save(update_fields=["role", "updated_at"])
    record_audit(
        action="membership.role_changed",
        actor=actor,
        organization=membership.organization,
        target_type="membership",
        target_id=str(membership.id),
        summary=f"{membership.user.email} in {membership.organization.name}: "
        f"{previous} → {new_role}",
        metadata={"from": previous, "to": new_role},
    )
    return membership


@transaction.atomic
def remove_membership(*, actor: User, membership: Membership) -> None:
    organization = membership.organization
    email = membership.user.email
    if membership.role == MembershipRole.ADMIN:
        remaining = (
            Membership.objects.filter(
                organization=organization, role=MembershipRole.ADMIN, is_active=True
            )
            .exclude(pk=membership.pk)
            .count()
        )
        if remaining == 0:
            raise ConflictError(
                detail=f"{organization.name} would be left with no administrator."
            )
    membership_id = str(membership.id)
    membership.delete()
    record_audit(
        action="membership.removed",
        actor=actor,
        organization=organization,
        target_type="membership",
        target_id=membership_id,
        summary=f"Removed {email} from {organization.name}",
    )


# --- Demo accounts ---------------------------------------------------------------------

# The seed command writes every demo account with this password. It is published through
# `/api/v1/auth/demo-accounts/` *only* when COMPASS_DEMO_MODE is on and the account is
# flagged synthetic, so a real deployment cannot publish a working credential list.
DEMO_PASSWORD = "compass-demo-2026"


def list_demo_accounts() -> list[dict]:
    """Seeded synthetic logins, for the local development sign-in helper."""
    if not settings.COMPASS_DEMO_MODE:
        return []
    accounts = []
    for user in (
        User.objects.filter(is_synthetic=True, is_active=True)
        .prefetch_related("memberships__organization")
        .order_by("system_role", "full_name")
    ):
        membership = user.memberships.filter(is_active=True).first()
        accounts.append(
            {
                "email": user.email,
                "password": DEMO_PASSWORD,
                "full_name": user.full_name,
                "system_role": user.system_role,
                "organization": membership.organization.name if membership else None,
                "description": _demo_description(user, membership),
            }
        )
    return accounts


def _demo_description(user: User, membership: Membership | None) -> str:
    if user.system_role == SystemRole.PLATFORM_ADMIN:
        return "Full administration: users, organizations, integrations and the audit trail."
    if user.system_role == SystemRole.FDE_LEAD:
        return "FDE command center plus knowledge approval and support analytics."
    if user.system_role == SystemRole.FDE:
        return "FDE command center: ticket inbox, investigation, issue clusters, playbooks."
    role = membership.role if membership else "viewer"
    org = membership.organization.name if membership else "no organization"
    if role == MembershipRole.ADMIN:
        return f"Customer administrator at {org}. Can approve change steps for their own cluster."
    if role == MembershipRole.ENGINEER:
        return f"Customer engineer at {org}. Submits tickets and runs Resolution Replay."
    return f"Customer viewer at {org}. Read-only access to tickets and knowledge."
