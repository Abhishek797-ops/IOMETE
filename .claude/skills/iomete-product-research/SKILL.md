---
name: iomete-product-research
description: Maintaining factual accuracy about IOMETE — the product knowledge base, source verification, the status vocabulary and the do-not-claim list. Use before writing or reviewing any customer-facing copy or product claim.
---

# IOMETE product research

## Source of truth

`docs/product-knowledge/knowledge.json`, verified against the log in
`docs/product-knowledge/sources.md`. **No customer-facing string may state a product fact that
is not traceable to an entry there.** If you need a fact that is not in the file, fetch the
official page, add the source and the entry, then use it.

Official starting points: `https://iomete.com/` and the documentation hub at
`https://iomete.com/resources` (note: `https://iomete.com/resources/getting-started/` returns
404 — use `/resources`). Always verify a URL resolves before citing it.

## Status vocabulary

| Status | Rendering obligation |
| --- | --- |
| `verified` | Normal, with a source link. |
| `vendor_claim` | Must be visibly attributed to IOMETE, never stated as a COMPASS finding. Applies to SOC 2 / HIPAA / GDPR statements and to the cost-saving multiples. |
| `needs_confirmation` | Labelled "Confirm with IOMETE". Excluded from generated recommendations. |
| `industry_concept` | Background education; no IOMETE attribution. |

## Never claim

The authoritative list is `do_not_claim` in `knowledge.json`. Summary: no pricing, no named
customers or case studies, no quantified savings for a specific prospect, no benchmarks or
latency figures, no SLAs, no certifications beyond the published statements, no integration or
storage backend that is not `verified`.

Two specifics worth remembering:

- IOMETE's homepage claims **2-5x** cost savings and its platform-overview page claims **2-3x**.
  They disagree. Cite them as vendor claims and acknowledge the discrepancy; never present
  either as a modelled saving.
- A COMPASS fit assessment is **an indicative assessment, not an official IOMETE compatibility
  determination**. Every assessment output must say so and must publish its rubric.

## Writing for non-technical readers

Lead with the problem in their language, then the mechanism. Use the analogies in
`knowledge.json.concepts` — they are deliberately consistent across the product (warehouse of
boxes → indexed boxes). Always name the honest trade-off: self-hosting means owning the
operations. A balanced explanation converts better than a brochure and survives a technical
follow-up.

## Verification workflow

Re-fetch sources → update entries and their `sources` arrays → bump `meta.last_verified` →
`python manage.py check_knowledge` → `pytest backend/knowledge`. If a page changed meaning,
**downgrade to `needs_confirmation` rather than guessing**.
