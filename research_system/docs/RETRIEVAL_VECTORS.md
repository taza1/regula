# Vector retrieval (FUT-020) — implementation status

Status: **mechanism implemented behind the existing interface; FUT-020 acceptance NOT met.** `TODO.md` is intentionally not ticked.

## What exists

- `src/embeddings.py`: `EmbeddingProvider` interface; `LocalHashEmbedder` (offline, deterministic, lexical only — a test adapter, not a semantic model); `ModelEndpointEmbedder` (uses `embeddings.create` on the already-configured OpenAI-compatible model client; bounded batches; errors are wrapped so provider detail is not leaked).
- `evidence_vectors` table in the local store: key `(tenant, project, evidence, model_id)`, with run ID, content hash and vector. It is derived data and always rebuildable.
- `EvidenceService.search_evidence_detailed`: modes `keyword` (FTS5/BM25, default), `semantic`, `hybrid` (weighted reciprocal-rank fusion). Eligibility, tenant, project and run filters are applied from the **live evidence record**, never from the index. Vectors whose content hash no longer matches are skipped and counted (`stale_vectors`). Missing/stale vectors, disabled embeddings, or a provider error make the search fall back to keyword and return `degraded_reason`.
- `EvidenceService.index_vectors`: idempotent, saves per batch (a provider failure keeps progress and a rerun resumes), `rebuild=true` recomputes for the active model. Vectors from a different `model_id` are ignored.
- API: `POST /runs/{run}/search` returns `mode`, `requested_mode`, `degraded_reason`; `POST /runs/{run}/index-vectors`. The background worker indexes after ingestion when an embedder is configured; failure does not fail the run.
- `src/retrieval_eval.py`: Precision@K, Recall@K, MRR, latency and degraded-case counts for keyword vs semantic vs hybrid. `passed` is `None` unless thresholds are supplied.

## Configuration (all defaults preserve keyword-only behavior)

| Setting | Default | Meaning |
|---|---|---|
| `RETRIEVAL_MODE` | `keyword` | mode when a request does not choose one |
| `RETRIEVAL_EMBEDDING_PROVIDER` | `none` | `none`, `local_hash`, or `model_endpoint` |
| `RETRIEVAL_CANDIDATE_LIMIT` | 200 | candidates per ranking before fusion |
| `RETRIEVAL_KEYWORD_WEIGHT` / `RETRIEVAL_SEMANTIC_WEIGHT` | 0.6 / 0.4 | fusion weights |
| `RETRIEVAL_FUSION_K` | 60 | RRF constant |
| `RETRIEVAL_MIN_SIMILARITY` | 0.05 | minimum cosine similarity |

`model_endpoint` sends evidence text to the configured model endpoint. Do not enable it until the data-handling decision below is made.

## Still open (not decided here)

- **ADR (FUT-001):** embedding model/version, dimensions, chunking, re-embedding policy, whether evidence text may be sent to the embedding endpoint, vector store ownership (local vs managed).
- **Gold set and thresholds:** a multi-domain, held-out retrieval gold set with agreed Precision@K / Recall@K / nDCG-or-MRR thresholds. No claim that hybrid beats keyword is made or supported; the harness only reports.
- **Run pinning:** active runs do not yet record the retrieval/index configuration they started with.
- **Metrics not covered by the harness:** date accuracy, duplicate leakage, independence grouping and contradiction discovery on vector results (see `quality_evals.py`).
- **Dedup of near-identical passages** in vector results, and **index version switching**.
