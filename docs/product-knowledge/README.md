# IOMETE Product Knowledge Directory

This directory is the **single source of truth** for every factual claim COMPASS makes about
IOMETE. It exists because COMPASS is customer-facing: a wrong statement about a product
capability in a sales conversation is worse than no statement at all.

## Files

| File | Purpose |
| --- | --- |
| `knowledge.json` | Machine-readable knowledge base. Served by the backend at `/api/v1/knowledge/product/` and consumed by the frontend explainer, architecture playground and fit finder. |
| `sources.md` | The verification log: every source URL, when it was fetched, and what was read from it. |

Nothing in the customer-facing UI may state a product fact that is not traceable to an entry
in `knowledge.json`.

## Status vocabulary

Every capability, technology, integration and storage backend carries a `status`:

| Status | Meaning | How the UI must render it |
| --- | --- | --- |
| `verified` | Read directly from an official IOMETE page listed in `sources`. | Normal presentation, with a source link. |
| `vendor_claim` | Published by IOMETE but not independently verifiable (compliance attestations, cost-saving multiples). | Explicitly labelled as a vendor claim, never as a COMPASS finding. |
| `needs_confirmation` | Referenced somewhere official but not documented well enough to rely on. | Labelled "Confirm with IOMETE" and excluded from recommendations. |
| `industry_concept` | General industry definition, not an IOMETE claim. | Presented as background education, no source link implied. |

## The `do_not_claim` list

`knowledge.json` ends with a `do_not_claim` array. These are assertions COMPASS must never
make — pricing, named customers, benchmarks, SLAs, quantified savings for a specific prospect.
Both the AI grounding prompt (`backend/aiengine/services/llm.py`) and the knowledge API
expose this list, and `backend/knowledge/tests.py` asserts it is non-empty and surfaced.

## Refreshing the knowledge base

1. Re-fetch each URL in `sources.md`.
2. Update the affected entries and their `sources` arrays.
3. Bump `meta.last_verified`.
4. Run `python manage.py check_knowledge` (backend) — it validates the schema, checks every
   `sources` reference resolves to a declared source id, and fails on an unknown `status`.
5. Run `pytest backend/knowledge` and commit.

If a page has moved or changed meaning, **downgrade the affected entry to
`needs_confirmation` rather than guessing**. An unconfirmed capability costs a sales
conversation one follow-up question; a fabricated one costs credibility.
