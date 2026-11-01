# IOMETE COMPASS — progress tracker

Last updated: 2026-11-01

## Verified state

| Check | Result |
| --- | --- |
| `cd backend && pytest` | **485 passed** (68 `security`, 30 `retrieval`, 208 `acceptance`) |
| `cd backend && ruff check .` | **clean** |
| `manage.py check` / `makemigrations --check` | **clean, no pending migrations** |
| `manage.py spectacular` | **115 operations, 0 warnings, 0 errors** |
| `manage.py check_knowledge --strict` | **valid** — 10 sources, 25 capabilities, 0 warnings |
| `manage.py seed_demo` | **19 tickets, 6 approved playbooks, 4 replay runs, 3 clusters, 5 prospects** |
| `cd frontend && npx tsc --noEmit` | **clean** |
| `cd frontend && npm run lint` | **clean** |
| `cd frontend && npm run build` | **succeeds** (3 routes built) |

Live API spot-checked end to end: login → tenant-scoped ticket list → similar-ticket
retrieval → playbook match → knowledge/lakehouse/fit endpoints.

## Phases

### Complete

**1 — Discovery and architecture.** Repository inspected (empty), IOMETE researched
against 10 official pages, stack chosen, `CLAUDE.md`, 7 Claude skills and 6 subagent
definitions written.

**2 — Product knowledge base.** `docs/product-knowledge/knowledge.json` with a status
vocabulary, resolvable citations and a `do_not_claim` guardrail list, plus a verification
log and a validating management command.

**4 — Backend foundation.** Django 6.1 + DRF 3.18, 11 apps, custom user, tenancy via a
single `for_user()` mechanism, JWT auth, RBAC, audit log, encrypted integration
credentials, 115-operation OpenAPI schema.

**5 — AI resolution engine.** Redaction → normalisation → fingerprinting → hybrid
retrieval (4 channels, weighted RRF, pgvector *or* numpy) → three separate confidences →
compatibility gate → grounded generation with a deterministic offline provider.

**6 — Resolution Replay and knowledge compounding.** Branching workflow engine with
enforced approval on system-changing steps, graph validation, extraction → FDE review →
approval → reuse, duplicate detection, versioning.

**8 — Integrations (backend).** Jira adapter + mock provider, IOMETE adapter speaking the
published Iceberg REST Catalog spec, honest `demo`/`configured`/`connected` state machine,
sync with retry and audit, HMAC-verified webhook.

**9 — Backend testing.** 485 tests. All 14 acceptance criteria covered at the service
*and* API layer.

### In progress

**2/3 — Frontend.** Foundation complete and building:

* Design tokens (`globals.css`): warm public surface, graphite operator chrome, emerald
  accent, dedicated trust/simulated/gated token families, dark mode, reduced-motion.
* Typed API client with one error type, in-memory tokens + single-flight refresh.
* Hooks written against React 19 rules (`useEffectEvent`, `useSyncExternalStore`;
  `useResource` derives `loading` rather than setting it in an effect).
* 60+ UI primitives across `primitives / forms / states / trust / data / overlays`,
  including the components that carry the product's honesty: `TrustNotice`, `GateNotice`,
  `ScoreTrio`, `MetricTile`, `SimulatedNotice`, `ClaimStatusBadge`, `EvidenceList`.
* `PublicShell`, `OperatorShell`, `DemoBanner`, landing page, login with demo-account
  picker.

**Remaining:** the 21 page bodies — `/explore`, `/architecture`, `/fit-finder`,
`/lakehouse-playground`, `/request-demo`, `/app/*` (5), `/fde/*` (7), `/admin/*` (5) — then
Playwright journeys, `docs/architecture.md`, `docs/api.md`, `docs/demo-walkthrough.md`,
`README.md`, and `docker-compose.yml`.

## Defects found and fixed during the build

Each was caught by a test or a lint rule, not by inspection:

1. **`validate_graph` looped forever** on a playbook whose `branches` described a cycle.
   The traversal accumulated a diagnostic *count*, making the state space infinite. Now a
   boolean, so it always terminates — and the cyclic playbook is correctly reported.
2. **Redaction was not idempotent.** Patterns matching the structure *around* a secret
   (`user:SECRET@host`) re-matched the placeholder, so re-scanning clean text reported
   phantom findings and `assert_redacted()` cried wolf.
3. **Resolution confidence ignored diagnosis confidence.** A verified fix for an unrelated
   problem scored 0.63 beside a diagnosis confidence of 0.05 — incoherent, and an
   invitation to apply the wrong fix. Now conditional on the diagnosis.
4. **Clustering grouped nothing.** Jaccard similarity against a *widening* union meant a
   cluster became progressively harder to join. Now containment against a narrowing core.
5. **Deprecated playbooks 404'd for customers.** Anyone who had followed one could not
   reopen it. `visible_to()` now includes them, flagged, while `trusted()` still excludes.
6. **`sqlite_master` was readable** in the SQL playground: the authorizer allowed reads
   generically. Internal tables are now denied explicitly.
7. **`PRAGMA query_only` was set before the data loaded**, so every query failed.
8. **An `Organization` annotation collided with a model property**, 500-ing the detail view.
9. **A sample query's chart hint named a column it did not return** — caught by a test that
   runs every sample and checks its chart against the real result columns.

## Known limitations

* **Page bodies are not written yet.** The shells, design system and API client are in
  place and building, but the 21 feature pages are the remaining work.
* **pgvector is untested against a live Postgres** in this session (SQLite throughout).
  The vendor-guarded migration and the `pgvector` query path exist and the backend reports
  `numpy` honestly; the Postgres path needs `docker compose up` to verify.
* **Connected IOMETE mode cannot execute SQL** — by design. IOMETE's documented query
  interfaces are driver-based (HiveServer2 JDBC, Spark Connect, Arrow Flight), so the
  adapter reads catalog metadata over the Iceberg REST spec and refuses SQL rather than
  returning synthetic rows under a connected label.
* **Celery is wired but unused.** Everything runs inline; the broker is optional.
* **`drf-spectacular` types ~30 rich endpoints as free-form `object`.** They return nested
  documents (a knowledge base, an architecture graph) where a generated schema would be
  weaker than the prose description plus `docs/api.md` examples.

## Architectural decisions

| Decision | Why |
| --- | --- |
| Embeddings in a portable `JSONField`; pgvector as a *derived* index via a vendor-guarded migration | Runs with zero infrastructure on SQLite and with real ANN search on Postgres, from one set of models. The backend used is always reported. |
| Hybrid retrieval, fused with weighted RRF on *ranks* | The four channels fail in different directions, and RRF means one channel's badly-scaled score cannot swamp the others. Fingerprint carries the highest weight: an exact shared error code is the strongest evidence in support search. |
| Three confidences, with resolution conditional on diagnosis | Conflating them is the characteristic failure of AI support tooling. |
| Unknown applicability is treated as *not applicable* | A wrong fix on a production cluster is the worst outcome available, so the gate is conservative by construction. |
| Deterministic demo providers for both LLM and embeddings | The product is fully demonstrable and genuinely *testable* with no credentials, and demo mode is disclosed rather than disguised. |
| Playbooks are data; nothing is ever executed | A structural test parses the execution engine's AST and fails on `subprocess`, `eval` or `os`. |
| Analytics computed at request time, never stored | No constant can masquerade as a measurement. Every figure reports its window, sample size, derivation and confidence. |
| SQL playground on per-request in-memory SQLite + authorizer | Real SQL execution — which teaches something — with writes denied below the parser and no reach into the application database. |
