# Competitive Intelligence V2 observability

Production has four distinct kinds of data:

- **Domain persistence:** `CompetitiveAnalysisRun`, report, source metadata/provenance and the
  evidence excerpts supplied to the report. These are Organization-owned PostgreSQL records.
- **Auron Run Telemetry:** a compact, sanitized, versioned JSON snapshot on that same run. This
  supports product inspection through the existing authorized run-detail API.
- **OpenTelemetry:** operational spans produced with the official Python API/SDK and optionally
  exported over OTLP. OpenTelemetry is not the storage or query interface for the product UI.
- **Offline evaluation:** frozen V2 cases, rankings, ground truth and quality metrics under
  `backend/evaluation`. Benchmark scripts do not create run rows or product telemetry snapshots.

```text
CompetitiveAnalysisRun
    -> telemetry JSONB (Auron product inspection)
    -> OpenTelemetry trace (optional operational export)
```

## Execution and correlation

Each admitted execution has its own root span `competitive_intelligence.analysis`, correlated
with `analysis_run_id`, `organization_id` and `pipeline_version`. User IDs, company names,
research queries, prompts, model response bodies, reports, headers and API keys are not attributes.
Only error types are recorded; exception messages and automatic exception stacktrace events are
disabled for these manual spans.

The hierarchy follows current execution order:

```text
competitive_intelligence.analysis
  question_generation
    llm.invoke
  web_research
    tavily.search (per question)
    source_acquisition (primary/secondary candidates)
      tavily.extract (per request/partial-result retry)
    deduplication
  source_processing
    chunking
    embeddings (batch embedding and indexing)
      embeddings.invoke (actual OpenAI SDK document batch)
    retrieval (per question, includes query embedding)
      embeddings.invoke (query embedding)
    context_building
  report_generation
    llm.invoke
```

Stages and provider calls use `perf_counter`, not database timestamps. Stage summaries aggregate
repeated calls. Durations overlap for parents and children and must not be added together to
calculate total duration. Total run duration includes lifecycle/report persistence through the
terminal outcome, excluding snapshot persistence and transport delivery.

Streaming binds tracing/recorder context separately for each synchronous iterator step, since
those steps can execute in different worker contexts. Context propagates into LangGraph nodes;
neither the recorder nor database sessions are stored in graph state. A pending run cancelled
before iteration receives a cancellation snapshot with no executed stages.

## Persisted snapshot and API

Migration `0009_ci_run_telemetry` adds one nullable JSONB column, `telemetry`, to
`competitive_analysis_runs`. Historical runs remain readable with `telemetry: null`.
The run's existing Organization boundary and authorization protect this field. No tracing table,
new permission or separate Inspector endpoint is introduced.

`GET /organizations/{organization_id}/modules/competitive-intelligence/analyses/{run_id}` now
includes a typed `telemetry` object with:

- schema version `1`, pipeline version, run ID, optional 32-character hexadecimal trace ID,
  terminal status, safe error type and total duration in milliseconds;
- stage summaries (name, calls, duration, failures, error type);
- models and provider calls (operation, latency, status, safe error type, nullable retry count);
- known input/output/cached token totals and the number of OpenAI calls with incomplete usage;
- versioned estimated USD costs and unavailable-call counts;
- question/search/source/deduplication/document/chunk/embedding/retrieval/context statistics;
- final evidence IDs, source keys, chunk IDs, cosine distances and original retrieval ranks.

Evidence IDs match `detail.evidence[].evidence_id`; source keys match
`detail.sources[].source_key`. Snapshot evidence contains references and scores only, never excerpt
text. Run listing remains a compact summary and does not include telemetry or report content.

Tavily search/extract requests enable `include_usage`. Calls retain candidate/selected counts,
depth, successful/missing extractions, observed credit usage and extraction retry attempts.
Extraction URLs omit credentials, query strings and fragments. No downloaded content is stored in
telemetry. Full source URLs and evidence text remain exclusively in the existing domain records.

OpenAI LLM usage is captured through a LangChain metadata-only callback, including structured
question generation. A client wrapper observes the actual synchronous embedding SDK batches
without changing LangChain tokenization, batching or query-call semantics. Document batches and
query embeddings are separate operations. Aggregate provider batches/embedded units include both;
index batches and chunk counts describe document indexing only. Missing usage stays null;
hidden SDK retries stay null
unless a callback exposes them. Async embedding adapters are not currently used/instrumented.

## Optional OTLP export

Dependencies explicitly pin the official API, SDK and OTLP/gRPC exporter. No vendor backend is
included. By default, a private SDK provider produces trace IDs without an external exporter; it
does not replace the global provider or configure Chroma's own telemetry.

Set these **process environment variables** before starting the backend, for example in PowerShell:

```powershell
$env:OTEL_TRACES_EXPORTER = 'otlp'
$env:OTEL_EXPORTER_OTLP_PROTOCOL = 'grpc'
$env:OTEL_EXPORTER_OTLP_ENDPOINT = 'https://your-collector.example:4317'
$env:OTEL_SERVICE_NAME = 'auron-backend'
```

Standard exporter variables also support signal-specific `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`,
headers, certificates, insecure transport and timeout. Configure secrets through the deployment's
environment/secret manager; never put them in source control. This implementation supports gRPC,
not OTLP/HTTP. Refer to the [official OTLP configuration](https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/).
These variables are consumed by the SDK from the process environment, not Auron's `.env` parser.
Configuration is initialized once on the first execution; changes require a process restart.

`OTEL_TRACES_EXPORTER=none` disables export (the default).
`OTEL_SDK_DISABLED=true` disables tracing entirely while product telemetry still works, with a null
trace ID. Invalid tracing configuration falls back to disabled tracing. Export uses a bounded SDK
batch processor; shutdown uses the SDK's process-exit hook. Export/processor errors never change
an analysis outcome. Expanding to HTTP export or a managed lifespan flush is a future refinement.

GenAI attribute mapping lives only in `telemetry.gen_ai_attributes`; it follows the
[OpenTelemetry GenAI conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md).
These conventions are evolving and can be revised without spreading changes across domain code.

## Cost estimates

`CI_PRICING_FILE` (process environment or Auron `.env`) selects a deployment-owned JSON rate card.
It is centralized, versioned and independent of the pipeline. All arithmetic uses `Decimal`;
amounts serialize as decimal strings. Rates below are **illustrative, not market prices**:

```json
{
  "version": "example-only-v1",
  "models": {
    "openai:gpt-4o-mini": {
      "input_per_million": "1.00",
      "cached_input_per_million": "0.50",
      "output_per_million": "2.00"
    },
    "openai:text-embedding-3-small": {"input_per_million": "0.10"}
  },
  "tavily_credit_usd": "0.01"
}
```

Use actual contractual rates and assign a new catalog version when updating them. An absent or
invalid catalog produces unavailable costs. Unknown model rates, missing token/cache usage or
missing Tavily credits also produce null per-call costs. The total is null when any call is
unpriced; a separately labelled known subtotal can remain available. No calls means unavailable,
not zero. These are estimates, not invoices, and do not account for provider billing adjustments.
Existing snapshots retain their original pricing version and calculated values.

## Failure boundaries and remaining limitations

Report/source/evidence completion remains atomic. Snapshot persistence uses a separate scoped,
short transaction after the domain outcome and before the terminal event. Snapshot failure logs a
safe warning and leaves a valid report completed; the detail may have null telemetry. Failed and
cancelled runs retain the available partial statistics. Provider work never holds a telemetry
transaction. There is no persisted low-level span database, payload capture or external UI lookup.

Hard process termination/database outages can prevent finalization and snapshot persistence.
Automatic orphan recovery, incremental live telemetry persistence, retries/backfill of missing
snapshots, frontend Inspector, workers/checkpoints and production quality judges remain out of scope.
