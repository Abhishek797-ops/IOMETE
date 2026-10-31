# CLAUDE.md — IOMETE COMPASS

> Keep this file short. Specialised knowledge lives in `.claude/skills/*/SKILL.md`.

## What this product is

**IOMETE COMPASS** — *Understand. Experience. Resolve. Improve.*

An AI-powered customer-enablement and Forward Deployed Engineer (FDE) productivity platform
for IOMETE, a sovereign (self-hosted) data lakehouse platform. It solves two problems:

1. **Enablement** — prospects do not understand what a data lakehouse is or whether IOMETE
   fits their infrastructure. COMPASS explains, demonstrates and assesses fit.
2. **Support repetition** — FDEs re-investigate problems that were already solved for another
   customer. COMPASS retrieves prior work, guides the customer through a verified resolution,
   and turns each new investigation into reusable knowledge.

The differentiator is **Resolution Replay + Knowledge Compounding**, not chat.

## Repository layout

```
backend/            Django 6 + DRF. All business logic in app `services/` packages.
  compass/          Project: settings/{base,dev,prod}.py, urls, asgi/wsgi
  accounts/         User (custom), Organization, Membership, AuditLog, RBAC
  prospects/        ProspectProfile, FitAssessment, ArchitectureRecommendation
  tickets/          Ticket, TicketEvent, TicketAttachment, ErrorFingerprint,
                    SimilarityMatch, IssueCluster
  playbooks/        ResolutionPlaybook, PlaybookStep, PlaybookExecution, KnowledgeApproval
  aiengine/         The AI layer. services/: normalization, redaction, embedding,
                    fingerprint, retrieval, ranking, evidence, knowledge_extraction, llm
  integrations/     IntegrationConfiguration + ticket/lakehouse provider adapters
  knowledge/        Serves docs/product-knowledge/knowledge.json; fit-assessment rubric
  lakehouse/        Synthetic lakehouse demo dataset + deterministic SQL engine
  analytics/        Support-effectiveness metrics
  common/           Base models, permissions, pagination, exception handler
frontend/           Next.js 16 App Router + TypeScript + Tailwind v4
  src/app/(public)  /, /explore, /architecture, /fit-finder, /lakehouse-playground, /request-demo
  src/app/(portal)  /app/*  — customer portal
  src/app/(fde)     /fde/*  — FDE command center
  src/app/(admin)   /admin/* — administration
  src/components/   ui/ (primitives), charts/, diagrams/, layout/, features/
  src/lib/          api client, auth, types, utils
docs/product-knowledge/   SOURCE OF TRUTH for all IOMETE product facts. Read the README.
docs/                     architecture.md, api.md, demo-walkthrough.md
```

## Development commands

```bash
# Everything, containerised (Postgres 17 + pgvector, Redis, backend, frontend)
docker compose up --build

# Backend, locally
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate && python manage.py seed_demo && python manage.py runserver

# Frontend, locally
cd frontend && npm install && npm run dev

# Tests
cd backend && pytest                    # unit + integration + tenant isolation + retrieval
cd frontend && npm run lint && npx tsc --noEmit
cd frontend && npx playwright test      # e2e journeys
```

Backend on `:8000`, frontend on `:3000`. API docs at `/api/docs/` (Swagger) and
`/api/schema/` (OpenAPI 3).

## Code conventions

- **API endpoints are versioned under `/api/v1/`.** No exceptions.
- **No business logic in DRF views or serializers.** Views validate, delegate to a service in
  `<app>/services/`, and serialize. Services are plain Python, take primitives or models,
  return dataclasses or models, and never touch `request`.
- **Every tenant-scoped model inherits `common.models.TenantOwnedModel`** and every queryset
  for one goes through `.for_user(user)`. Never filter tenancy in a view by hand.
- TypeScript: `strict` on. No `any` without a comment explaining why. Server Components by
  default; `"use client"` only where interactivity requires it.
- Tailwind: use design tokens from `src/styles/globals.css`. No arbitrary hex values in JSX.
- Python: type hints on all service functions. `ruff` clean.

## Security rules (non-negotiable)

1. **Tenant isolation is a security boundary.** A customer must never see another
   organization's tickets, attachments, assessments, executions or internal FDE notes.
   Cross-tenant reads are permitted *only* through `ResolutionPlaybook` rows that are
   `approved` and `is_shared`, and through anonymised aggregate metrics.
2. **Never execute LLM-generated commands.** Playbook steps are data reviewed by a human.
   Diagnostic commands are *displayed for the user to run*, never executed by the backend.
3. **Redact before persist, redact before embed.** Every inbound ticket body goes through
   `SensitiveDataRedactionService` before it is stored, embedded or sent to an LLM provider.
4. **Never log secrets.** No API keys, tokens, passwords or full diagnostic payloads in logs.
   Integration credentials are encrypted at rest (`common.crypto`) and never returned by the API.
5. **Changes require authorization.** A playbook step with `step_type` in
   `{change_requiring_approval, remediation}` cannot be marked complete without an
   `approval_granted_by` that has the right role. Enforced in the service, tested.
6. **Never fake a live connection.** The IOMETE and Jira adapters report
   `mode=demo` unless real, verified credentials are configured. There is no code path that
   reports `connected` without a successful live handshake.
7. No secrets in source control. `.env.example` documents every variable; `.env` is ignored.

## Factual accuracy rules

Everything COMPASS says about IOMETE must trace to `docs/product-knowledge/knowledge.json`.
Read `docs/product-knowledge/README.md` before touching customer-facing copy. Respect the
`status` vocabulary (`verified` / `vendor_claim` / `needs_confirmation` / `industry_concept`)
and the `do_not_claim` list. No invented features, integrations, pricing, customers,
benchmarks or SLAs.

All tickets, clusters and playbooks shipped by `seed_demo` are **synthetic**. The UI must say
so wherever they appear.

## Important implementation decisions

| Decision | Why |
| --- | --- |
| Embeddings stored in a portable `JSONField`, with an **optional** pgvector index table created by a vendor-guarded migration | The product must run on SQLite with zero infrastructure *and* use real pgvector ANN search on Postgres. `HybridRetrievalService` picks the backend at runtime and reports which one it used. |
| Hybrid retrieval = vector + lexical BM25-ish + error fingerprint + metadata gating, fused with weighted RRF | Embedding-only similarity is wrong for support search: an exact error-code match matters more than prose similarity, and an incompatible version must be gated out regardless of score. |
| Three separate scores: `similarity`, `diagnosis_confidence`, `resolution_confidence` | Conflating them is the central failure mode of AI support tools. A paraphrase can score 0.9 similarity while the root cause is unrelated. |
| Deterministic `DemoLLMProvider` when no API key is set | The whole product must be demonstrable with no credentials. Demo mode is explicit in the API response (`provider: "demo"`), never disguised. |
| Default `AUTH` is JWT (SimpleJWT) in `Authorization: Bearer`, with a session fallback for Django admin | Frontend is a separate origin; cookie CSRF across origins adds risk without benefit here. |

## Progress

`PROGRESS.md` is the live tracker: completed phases, known issues, test results,
architectural decisions. Update it when you finish a phase — do not mark anything complete
that has not been run and verified.
