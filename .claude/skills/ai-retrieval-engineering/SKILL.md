---
name: ai-retrieval-engineering
description: RAG and support-search engineering for this repo — hybrid retrieval, pgvector, embeddings, error fingerprinting, metadata gating, reranking, grounded generation and the three-confidence model. Use when working in backend/aiengine.
---

# AI retrieval engineering — IOMETE COMPASS

## Why embedding-only search is wrong here

Support search is not document search. Three properties break pure cosine similarity:

1. **An exact error token beats prose similarity.** `OOMKilled` or
   `NoSuchTableException` appearing in both tickets is far stronger evidence than two
   paragraphs that read alike.
2. **Compatibility is a gate, not a score.** A perfect textual match on IOMETE 2.1 / AWS is
   *not* a recommendation for a 3.19 / on-prem ticket. Gating happens after scoring and can
   veto a high score outright.
3. **Prose similarity is not root-cause identity.** Two "Spark executor keeps restarting"
   tickets can be memory exhaustion and a missing image pull secret.

## The pipeline

```
raw ticket
  → SensitiveDataRedactionService   (before storage, embedding, or any LLM call)
  → TicketNormalizationService      (error codes, phrases, component, version, env, symptoms)
  → ErrorFingerprintService         (stable sha256 over normalized error signature)
  → HybridRetrievalService          (4 recall channels, below)
  → SimilarityRankingService        (weighted RRF + feature boosts → similarity score)
  → CompatibilityGate               (version/env/component → gated | penalised | clean)
  → RootCauseEvidenceService        (per-match evidence: what matched and why)
  → ResolutionPlaybookService       (approved + non-deprecated + applicable only)
  → grounded answer or escalation
```

### Recall channels

| Channel | Mechanism | Weight |
| --- | --- | --- |
| Vector | pgvector `<=>` cosine on Postgres; numpy cosine on SQLite | 1.0 |
| Lexical | Postgres `websearch_to_tsquery` + `ts_rank`; portable token-overlap BM25-ish fallback | 0.9 |
| Fingerprint | exact + prefix match on `ErrorFingerprint.digest` | 1.4 |
| Metadata | component / category / environment structured match | 0.6 |

Fused with weighted Reciprocal Rank Fusion (`k=60`), then feature boosts for verified
resolution, recency, and resolution quality.

`HybridRetrievalService.search()` returns `RetrievalResult` carrying `backend_used`
(`"pgvector"` or `"numpy"`) and per-channel contributions. **The API surfaces this** — we never
hide which backend answered.

## Three separate confidences — never collapse them

| Score | Means | Driven by |
| --- | --- | --- |
| `similarity` | How alike the two tickets look | retrieval fusion |
| `diagnosis_confidence` | How sure we are of the *root cause* | evidence collected, fingerprint match, symptom overlap, compatibility |
| `resolution_confidence` | How sure we are the fix will work *here* | playbook verification status, review age, applicability match, historical success rate |

Serializers expose all three. The UI renders them separately with their own explanations. A high
similarity with low diagnosis confidence must read as "looks related, cause unconfirmed".

## Embeddings

`EmbeddingService` is an adapter: `GeminiEmbeddingProvider` (`gemini-embedding-001`) when
`GEMINI_API_KEY` is set, otherwise `HashingEmbeddingProvider` — a deterministic, seeded
feature-hashing embedder so retrieval is genuinely testable and demoable offline. Dimension is
fixed by `EMBEDDING_DIM` and asserted at write time; a dimension change requires a re-embed
management command, never a silent mismatch.

Store the vector in `embedding` (`JSONField`) as the portable source of truth. On Postgres a
vendor-guarded migration also maintains `aiengine_vector_index` with a real `vector` column and
an HNSW index, kept in sync by `EmbeddingIndexService`.

## Grounded generation

- Every generated sentence must be attributable to a retrieved ticket, an approved playbook, or
  `docs/product-knowledge/knowledge.json`. The prompt supplies numbered sources; the model is
  instructed to cite ids; `GroundingValidator` strips or flags uncited claims.
- Structured output only (JSON schema per call site). Never free-form text parsed by regex.
- When evidence is insufficient: ask a diagnostic question, offer alternatives, or escalate.
  Those are first-class return values, not fallbacks.

## Never

Invent a ticket id, a fix, or an IOMETE capability. Treat similarity as root-cause certainty.
Surface an unapproved or deprecated playbook as a trusted resolution. Let one tenant's retrieval
see another tenant's private tickets — `for_user` scoping is applied *inside* every recall
channel, including the raw SQL ones. Embed un-redacted text. Execute a command a model produced.
