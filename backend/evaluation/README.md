
# Competitive Intelligence Evaluation

This directory contains versioned benchmark data and persisted evaluation results. Runtime
Python code remains under `app/scripts/competitive_intelligence_benchmark`.

Production Competitive Intelligence now uses the same V2 chunking, batched embedding, Chroma
retrieval, grounded context, and report implementations. Production acquires live documents,
deduplicates sources across its generated questions while retaining discovery metadata, and
disposes of its tenant/execution-isolated collection; it does not read these fixtures or execute
evaluation judges. Benchmark captures use isolated single-question cases and reuse their one query
embedding for both observed dimensionality and retrieval.

Live production analyses now persist tenant-owned runs, reports, source metadata, and retrieved
evidence excerpts in PostgreSQL through the module service. Benchmark scripts continue to operate
on their existing versioned files and do not create `CompetitiveAnalysisRun` rows or persist graph
state. Neither stored benchmark artifacts nor benchmark metrics are production run history.
Production's compact Run Telemetry snapshots and optional OpenTelemetry traces describe execution,
usage and retrieval statistics, not benchmark quality or groundedness. See
[`docs/COMPETITIVE_INTELLIGENCE_OBSERVABILITY.md`](../../docs/COMPETITIVE_INTELLIGENCE_OBSERVABILITY.md).

Frozen V2 data records the historical capture configuration (including `include_answer: true`),
even though current live Tavily acquisition disables answer generation. The captured content,
ground truth, reports, and metrics remain unchanged. Recapturing with changed acquisition semantics
requires a new benchmark version; never rewrite frozen configuration to describe current production.

Never store API keys, `.env` files, raw embeddings, persistent Chroma databases, or disposable
caches here.
