
# Competitive Intelligence V2 Benchmark

V2 is a frozen-source benchmark for five canonical competitive-intelligence questions. Retrieval
metrics are deterministic after search fixtures and evaluation rankings have been captured.
Generation metrics are reported separately as LLM-judge observations.

## Workflow

Run commands from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m `
  app.scripts.competitive_intelligence_benchmark.migrate_v2_benchmark
.\.venv\Scripts\python.exe -m `
  app.scripts.competitive_intelligence_benchmark.prepare_benchmark_case `
  --case <case_id> capture-search
.\.venv\Scripts\python.exe -m `
  app.scripts.competitive_intelligence_benchmark.prepare_benchmark_case `
  --case <case_id> build-candidates
.\.venv\Scripts\python.exe -m `
  app.scripts.competitive_intelligence_benchmark.prepare_benchmark_case `
  --case <case_id> validate-ground-truth
.\.venv\Scripts\python.exe -m `
  app.scripts.competitive_intelligence_benchmark.prepare_benchmark_case `
  --case <case_id> capture-evaluation
.\.venv\Scripts\python.exe -m `
  app.scripts.competitive_intelligence_benchmark.evaluate_benchmark --all --mode full
```

`capture-search` is the only operation that calls Tavily. `build-candidates` and retrieval
evaluation are offline. `capture-evaluation` reads only the frozen search fixture and may call
OpenAI for embeddings and report generation. Generation evaluation may call the configured LLM
judges.

## Freeze policy

While status is `draft`, changed artifacts require explicit `--allow-overwrite`. Once status is
`frozen`, canonical questions, source fixtures, candidates, ground truth, ranking, evidence IDs,
reports, configuration, results, and checksums are immutable. Corrections require a new benchmark
version.
