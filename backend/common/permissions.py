"""
Permission classes.

Every mutating endpoint enforces its role requirement here, on the server. The frontend
hiding a button is cosmetic — an attacker uses curl.
"""

from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsAuthenticatedAndActive(BasePermission):
    """Default permission. Rejects anonymous and deactivated accounts."""

    message = "Authentication with an active account is required."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.is_active)


class HasRole(BasePermission):
    """Base for system-role checks. Build concrete classes with `has_role()`."""

    required_roles: tuple[str, ...] = ()
    message = "Your role does not permit this action."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        if not self.required_roles:
            return True
        return user.system_role in self.required_roles


def has_role(*roles: str) -> type[HasRole]:
    """
    Build a permission class requiring one of `roles` on `User.system_role`.

    Usage: ``permission_classes = [has_role("fde", "platform_admin")]``

    A factory rather than an instance because DRF instantiates permission classes itself.
    """
    if not roles:
        raise ValueError("has_role() requires at least one role.")
    return type(
        "HasRole_" + "_".join(roles),
        (HasRole,),
        {
            "required_roles": tuple(roles),
            "message": "This action requires one of these roles: " + ", ".join(roles) + ".",
        },
    )


class IsIometeStaff(BasePermission):
    """FDE, FDE lead or platform admin."""

    message = "This endpoint is restricted to IOMETE staff (FDE or platform admin)."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.is_iomete_staff)


class IsPlatformAdmin(BasePermission):
    message = "This endpoint is restricted to platform administrators."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user and user.is_authenticated and user.is_active
            and user.system_role == "platform_admin"
        )


class CanApproveKnowledge(BasePermission):
    """
    Knowledge approval is the trust boundary of the whole compounding loop.

    Only an FDE, FDE lead or platform admin may approve, reject or deprecate a playbook.
    A customer — however senior inside their own organization — must not be able to mark
    a resolution as verified for other customers.
    """

    message = "Only an FDE or platform administrator can approve or reject knowledge."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        return user.system_role in {"fde", "fde_lead", "platform_admin"}


class IsSameOrganization(BasePermission):
    """
    Object-level tenant check.

    Defence in depth: a `for_user()`-scoped queryset should already have produced a 404,
    but the authorization decision is made explicitly here rather than inferred from the
    absence of a row.
    """

    message = "This resource belongs to a different organization."

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if user.is_iomete_staff:
            return True
        organization_id = getattr(obj, "organization_id", None)
        if organization_id is None:
            return True
        return organization_id in user.organization_ids()


class ReadOnlyForCustomer(BasePermission):
    """Customers may read; only IOMETE staff may write."""

    message = "Customers have read-only access to this resource."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        if request.method in SAFE_METHODS:
            return True
        return user.is_iomete_staff


class IsOrganizationAdminOrStaff(BasePermission):
    """
    An organization's own admin, or IOMETE staff.

    Used for actions a customer may take for their own tenant (inviting a colleague,
    approving a change step on their own cluster) but not for another tenant.
    """

    message = "This action requires organization-admin rights or IOMETE staff."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        return user.is_iomete_staff or user.has_membership_role("admin")

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if user.is_iomete_staff:
            return True
        organization_id = getattr(obj, "organization_id", None)
        if organization_id is None:
            return False
        return user.has_membership_role("admin", organization_id=organization_id)
