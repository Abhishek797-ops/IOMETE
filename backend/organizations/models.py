"""
No models here by design.

`Organization`, `Membership` and `AuditLog` live in `accounts.models` because
`common.models.TenantOwnedModel` has a foreign key to `accounts.Organization`; defining it
here would create a circular dependency between the two apps. This module exists so the
app layout is explicit rather than leaving a reader to wonder where the model went.
"""
