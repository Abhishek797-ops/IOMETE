---
name: qa-release
description: Test strategy and release verification for this repo — backend tests, retrieval tests, tenant isolation, Playwright journeys, accessibility and responsive checks. Use when writing tests or verifying a milestone.
---

# QA and release — IOMETE COMPASS

## Principle

Test behaviour that would embarrass us if it broke, not lines of code. A retrieval test that
asserts "returns 5 results" is worthless; one that asserts "a paraphrased description still
retrieves the right historical ticket" is the product.

## Commands

```bash
cd backend  && pytest -q                      # all
cd backend  && pytest -q -m retrieval         # retrieval quality
cd backend  && pytest -q -m security          # tenancy + authz
cd frontend && npm run lint && npx tsc --noEmit
cd frontend && npx playwright test
cd frontend && npx playwright test --project=mobile
```

## The fourteen acceptance tests

These map 1:1 to `backend/*/tests/` and are the release gate:

1. A customer cannot access another customer's private ticket (list, detail, update, similar, analytics).
2. A paraphrased issue description still retrieves the relevant historical ticket.
3. An exact error fingerprint measurably increases match relevance over prose-only similarity.
4. A ticket with a similar error but an incompatible version/environment is gated, not recommended.
5. An unverified (draft/rejected/deprecated) solution never enters trusted playbook search.
6. A customer can complete a guided troubleshooting workflow end to end, including a branch.
7. An unresolved issue produces an escalation carrying the full diagnostic summary.
8. An FDE can approve a knowledge draft; a customer role cannot.
9. An approved playbook becomes available to an eligible future ticket.
10. A deprecated playbook is not recommended as an active fix.
11. Missing AI credentials do not break demo mode — retrieval and generation still answer, flagged `provider: "demo"`.
12. Missing Jira credentials do not break ticket workflows — the adapter reports `mode: "demo"`.
13. Connected IOMETE mode never reports `connected` without a real handshake.
14. A `change_requiring_approval` step cannot be completed without a valid approval.

## Playwright journeys

| Journey | Path |
| --- | --- |
| Customer enablement | `/` → `/explore` (pick persona) → `/fit-finder` (complete wizard) → architecture recommendation → `/request-demo` |
| Support resolution | `/app/support` (submit ticket) → similar tickets → Resolution Replay → resolved **and** escalated variants |
| FDE | login → `/fde/tickets` → investigate → resolve → generate draft → `/fde/knowledge-review` → approve → `/fde/analytics` |
| Lakehouse demo | `/lakehouse-playground` → inspect schema → run sample query → visualise |

Each journey asserts on user-visible outcomes, not on implementation selectors. Use
`getByRole` / `getByLabel`. Add `data-testid` only where no accessible selector exists — and if
that happens, it is usually an accessibility bug worth fixing instead.

## Non-functional checks

- **Responsive**: 375 (mobile), 768 (tablet), 1440 (desktop). Assert no horizontal overflow:
  `document.documentElement.scrollWidth <= innerWidth`.
- **Accessibility**: `@axe-core/playwright` on every top-level route, zero serious/critical
  violations. Keyboard-only pass through the Fit Finder and Resolution Replay.
- **Console**: zero errors and zero React warnings during the journeys — the Playwright setup
  fails the test on an unexpected console error.
- **Demo-mode indicator** visible wherever synthetic data or a simulated integration appears.

## Before claiming done

Run it. Paste the real output into `PROGRESS.md`. Never mark a phase complete on the strength of
having written the code.
