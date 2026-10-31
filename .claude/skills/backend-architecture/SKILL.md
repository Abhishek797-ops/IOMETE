---
name: backend-architecture
description: Django 6 + DRF architecture for this repo — service layers, model conventions, tenancy, permissions, serializers, transactions and API shape. Use when adding or reviewing anything under backend/.
---

# Backend architecture — IOMETE COMPASS

## The one rule

**Views do not contain business logic.** A DRF view may: check permissions, validate input with
a serializer, call exactly one service function, serialize the result, map a domain exception to
an HTTP status. Everything else lives in `<app>/services/`.

Services are plain Python. They never import `rest_framework`, never touch `request`, and are
unit-testable without HTTP. They take primitives or model instances and return dataclasses or
model instances.

```python
# tickets/views.py
class TicketViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        return Ticket.objects.for_user(self.request.user).select_related("organization")

    @action(detail=True, methods=["post"])
    def escalate(self, request, pk=None):
        ticket = self.get_object()
        s = EscalateSerializer(data=request.data); s.is_valid(raise_exception=True)
        result = escalation.escalate_ticket(ticket, request.user, **s.validated_data)
        return Response(EscalationSerializer(result).data, status=201)
```

## Models

- Everything inherits `common.models.BaseModel`: `id` (UUIDv4 pk), `created_at`, `updated_at`.
- Tenant-scoped models inherit `common.models.TenantOwnedModel`, which adds a non-null
  `organization` FK and installs `TenantQuerySet` as the default manager.
- `Model.objects.for_user(user)` is the **only** sanctioned way to scope a queryset. It returns
  everything for a staff/admin user, the user's organizations' rows for a customer, and
  assigned-plus-shared rows for an FDE. Never hand-filter `organization` in a view.
- Use `TextChoices` for every enum. Index every field used in a filter or ordering.
- `related_name` is always set and always plural.

## Permissions

`common/permissions.py` provides `IsAuthenticatedAndActive`, `HasRole(*roles)`,
`IsSameOrganization`, `IsFdeOrAdmin`, `ReadOnlyForCustomer`. Roles live on `Membership.role`
(`customer_viewer`, `customer_engineer`, `customer_admin`, `fde`, `fde_lead`, `platform_admin`).

Object permissions are checked in `has_object_permission`, not inferred from the queryset — a
404 from a scoped queryset is good defence but not the authorization decision.

**Role checks happen on the server.** The frontend hiding a button is cosmetic.

## Transactions

Any operation writing more than one row is wrapped in `transaction.atomic()`. Operations that
also write an `AuditLog` must include it in the same atomic block — an action that is not
audited did not happen. Use `select_for_update()` when advancing a `PlaybookExecution`.

## Serializers

Separate read and write serializers when they differ (`TicketSerializer` /
`TicketCreateSerializer`). Never expose: `password`, `IntegrationConfiguration.credentials`,
`Ticket.raw_diagnostics`, `TicketEvent.internal_note` to a customer role. Enforce with explicit
field lists, never `fields = "__all__"`.

## API shape

- Versioned under `/api/v1/`.
- Errors come from `common.exceptions.compass_exception_handler` in the shape
  `{"error": {"code": "...", "message": "...", "details": {...}}}`. `code` is a stable
  machine-readable slug the frontend switches on.
- Cursor-free page-number pagination, `?page=&page_size=` capped at 100.
- Every endpoint documented via `drf-spectacular` `@extend_schema` with an example.
- Throttling: `AnonRateThrottle` on public endpoints (fit assessment, demo request),
  `ScopedRateThrottle` scope `ai` on anything invoking retrieval or an LLM.

## Migrations

One logical change per migration. Vendor-conditional SQL guards on
`schema_editor.connection.vendor` so the SQLite path stays clean — see
`aiengine/migrations/0002_pgvector_index.py` for the pattern. Never edit an applied migration.
