---
name: security-review
description: Security review checklist for this repo — tenant isolation, authorization, secrets, sensitive-data handling, injection surfaces and AI-specific risks. Use when reviewing a change that touches auth, tenancy, integrations, the AI layer or any API surface.
---

# Security review — IOMETE COMPASS

## Threat model in one line

Multiple customer organizations share one deployment, submit diagnostic text that may contain
secrets, and receive AI-generated guidance about changing production infrastructure.

## Tenant isolation (the primary boundary)

- Every tenant-scoped queryset goes through `Model.objects.for_user(user)`. Grep for
  `.objects.all()` and `.objects.filter(` in views — each one is a finding until justified.
- Check the **raw SQL** paths too. Hybrid retrieval's lexical and pgvector channels build SQL;
  both must apply the organization predicate inside the query, not filter afterwards.
- Object-level: a scoped queryset returning 404 is defence in depth, not the authorization
  decision. `has_object_permission` must also be correct.
- Cross-tenant reads are legitimate **only** for `ResolutionPlaybook` rows that are
  `approved` and `is_shared`, and for anonymised aggregates. Raw private customer logs must
  never become global knowledge.
- Test required: `tickets/tests/test_tenant_isolation.py` must cover list, retrieve, update,
  similar-search, execution and analytics for a cross-tenant actor.

## Authorization

- Role checks on the server for every mutating endpoint. Frontend gating is cosmetic.
- Privilege escalation: can a `customer_engineer` set their own `Membership.role`? Can they
  approve a playbook? Grant a step approval? Read `TicketEvent.internal_note`? Each is a test.
- `change_requiring_approval` / `remediation` steps cannot complete without a valid
  `approval_granted_by` of sufficient role.

## Secrets and sensitive data

- `IntegrationConfiguration.credentials` is encrypted at rest via `common.crypto` (Fernet,
  key from `COMPASS_ENCRYPTION_KEY`) and is **write-only** in the API — never serialized back.
- `SensitiveDataRedactionService` runs before persist, before embed, before any LLM call. It
  covers: AWS keys, bearer/JWT tokens, private key blocks, passwords in connection strings,
  emails, IPv4/IPv6, S3 URIs with embedded credentials, Kubernetes secret values, and
  high-entropy tokens. Add a test case for every new pattern.
- Logging: no API keys, tokens, passwords, or full diagnostic payloads. `settings.LOGGING`
  installs a redacting filter; verify new log calls pass through it.
- `.env` ignored; `.env.example` documents every variable with a safe placeholder. No production
  credential may appear in seed data.

## Injection and input

- No string-formatted SQL. The lexical retrieval channel uses parameterised
  `websearch_to_tsquery`. The lakehouse demo SQL runs through a **restricted parser** that
  allows only `SELECT` against a fixed in-memory dataset — it never reaches the real database.
- File uploads: extension and MIME allowlist, size cap, content-type sniff, stored outside the
  web root with a generated name, never served from a user-controlled path.
- Zod on the client and a serializer on the server. Client validation is UX, not a control.

## Transport and headers

CORS allowlist from `CORS_ALLOWED_ORIGINS` — never `*` with credentials. JWT in
`Authorization: Bearer`, short-lived access token, rotating refresh with blacklist. CSRF applies
to the session-authenticated Django admin. Rate limits: anon throttle on public endpoints, `ai`
scope throttle on retrieval/LLM endpoints, login throttle.

## AI-specific risks

- **Prompt injection via ticket text.** Ticket bodies are untrusted data. The system prompt
  states that retrieved content is data, never instruction. Never let retrieved text select a
  tool or change the output schema.
- **No execution of model output.** Ever. Commands are displayed, not run.
- **Cross-tenant leakage via retrieval.** The highest-severity failure mode in this product.
  Scope inside the recall channels.
- **Unverified output presented as verified.** An AI-generated playbook draft is
  `approval_status=draft` and must be visually distinct from `approved` everywhere it appears.
- **False connection state.** No code path may report an IOMETE or Jira connection as
  `connected` without a successful live handshake against real configured credentials.

## Review output

Report findings as: severity, file:line, concrete failure scenario (inputs → wrong outcome),
and the fix. Verify each finding against the code before reporting it.
