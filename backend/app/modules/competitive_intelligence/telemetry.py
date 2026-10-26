"""Compact product telemetry and manual spans. No prompts, queries, pages or reports."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import RLock
from time import perf_counter
from urllib.parse import urlsplit, urlunsplit

from langchain_core.callbacks import BaseCallbackHandler
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import SpanKind, StatusCode

from app.config import get_settings
from app.core.tracing import get_tracer, safely

from .cost_estimation import PricingCatalog, estimate_run, load_pricing
from .telemetry_schemas import (
    EvidenceStatistic,
    ProviderCall,
    RunStatistics,
    RunTelemetry,
    StageSummary,
    TokenSummary,
)

logger = logging.getLogger(__name__)
_current = ContextVar("ci_run_telemetry", default=None)
_embedding_operation = ContextVar("ci_embedding_operation", default="document_embedding")


def safe_url(value: str) -> str:
    parts = urlsplit(value)
    # Omit credentials, query strings and fragments, which can contain access tokens.
    return urlunsplit((parts.scheme, parts.hostname or "", parts.path, "", ""))


def gen_ai_attributes(call: ProviderCall) -> dict:
    """Isolate evolving GenAI semantic conventions from all domain stages."""
    attrs = {
        "gen_ai.provider.name": call.provider,
        "gen_ai.operation.name": ("embeddings" if "embedding" in call.operation else "chat"),
        "auron.provider.operation": call.operation,
    }
    for key, value in (
        ("gen_ai.request.model", call.model),
        ("gen_ai.usage.input_tokens", call.input_tokens),
        ("gen_ai.usage.output_tokens", call.output_tokens),
        ("gen_ai.usage.cache_read.input_tokens", call.cached_input_tokens),
        ("error.type", call.error_type),
    ):
        if value is not None:
            attrs[key] = value
    return attrs


class RunRecorder:
    def __init__(self, run):
        self.run = run
        self.started = perf_counter()
        self.duration = None
        self.stages = {}
        self.calls = []
        self.statistics = RunStatistics()
        self.evidence = []
        self.lock = RLock()
        self.tracer = safely(get_tracer) or trace.NoOpTracerProvider().get_tracer("auron")
        self.root = (
            safely(
                self.tracer.start_span,
                "competitive_intelligence.analysis",
                context=Context(),
                attributes={
                    "analysis_run_id": str(run.id),
                    "organization_id": str(run.organization_id),
                    "pipeline_version": run.pipeline_version,
                },
            )
            or trace.INVALID_SPAN
        )

    @contextmanager
    def bind(self):
        token = _current.set(self)
        # Bind only for each synchronous iterator step. Never keep a ContextVar token
        # across yield: streaming steps may execute in different worker contexts.
        try:
            with trace.use_span(
                self.root, end_on_exit=False, record_exception=False, set_status_on_exception=False
            ):
                yield
        finally:
            _current.reset(token)

    def finish(self, status: str, error_type: str | None = None):
        if self.duration is not None:
            return
        self.duration = (perf_counter() - self.started) * 1000
        safely(self.root.set_attribute, "auron.run.status", status)
        safely(
            self.root.set_attributes,
            {
                f"auron.rag.{key}": value
                for key, value in self.statistics.model_dump().items()
                if value is not None
            },
        )
        if error_type:
            safely(self.root.set_attribute, "error.type", error_type)
        safely(self.root.set_status, StatusCode.ERROR if status == "failed" else StatusCode.OK)
        safely(self.root.end)

    def snapshot(self, status: str, error_type: str | None = None) -> RunTelemetry:
        try:
            pricing = load_pricing(get_settings().ci_pricing_file)
        except Exception:
            logger.warning("Run pricing unavailable")
            pricing = PricingCatalog(version="unavailable")
        tokens = TokenSummary(
            known_input_tokens=sum(call.input_tokens or 0 for call in self.calls),
            known_output_tokens=sum(call.output_tokens or 0 for call in self.calls),
            known_cached_input_tokens=sum(call.cached_input_tokens or 0 for call in self.calls),
            calls_with_unknown_usage=sum(
                call.input_tokens is None
                or (
                    "embedding" not in call.operation
                    and (call.output_tokens is None or call.cached_input_tokens is None)
                )
                for call in self.calls
                if call.provider == "openai"
            ),
        )
        span_context = self.root.get_span_context()
        return RunTelemetry(
            analysis_run_id=self.run.id,
            pipeline_version=self.run.pipeline_version,
            trace_id=f"{span_context.trace_id:032x}" if span_context.is_valid else None,
            status=status,
            error_type=error_type,
            total_duration_ms=self.duration or (perf_counter() - self.started) * 1000,
            stages=list(self.stages.values()),
            models=sorted({call.model for call in self.calls if call.model}),
            provider_calls=self.calls,
            tokens=tokens,
            cost=estimate_run(self.calls, pricing),
            statistics=self.statistics,
            evidence=self.evidence,
        )


def stat(*, add=False, **values):
    recorder = _current.get()
    if recorder is None:
        return
    try:
        with recorder.lock:
            for key, value in values.items():
                if add:
                    value += getattr(recorder.statistics, key) or 0
                setattr(recorder.statistics, key, value)
                if value is not None:
                    safely(trace.get_current_span().set_attribute, f"auron.rag.{key}", value)
    except Exception:
        logger.warning("Run statistics unavailable")


def evidence_statistics(evidence):
    recorder = _current.get()
    if recorder is not None:
        recorder.evidence = [
            EvidenceStatistic(
                evidence_id=f"E{i}",
                source_key=item.source_id,
                chunk_id=item.chunk_id,
                distance=item.distance,
                retrieval_rank=item.rank,
            )
            for i, item in enumerate(evidence, start=1)
        ]
        safely(
            trace.get_current_span().set_attributes,
            {
                "auron.evidence.ids": [item.evidence_id for item in recorder.evidence],
                "auron.evidence.source_keys": [item.source_key for item in recorder.evidence],
                "auron.evidence.distances": [item.distance for item in recorder.evidence],
            },
        )


@contextmanager
def measure(name: str, *, client=False):
    recorder = _current.get()
    if recorder is None:
        yield trace.INVALID_SPAN
        return
    started = perf_counter()
    span = (
        safely(
            recorder.tracer.start_span, name, kind=SpanKind.CLIENT if client else SpanKind.INTERNAL
        )
        or trace.INVALID_SPAN
    )
    error_type = None
    try:
        with trace.use_span(
            span, end_on_exit=False, record_exception=False, set_status_on_exception=False
        ):
            yield span
    except BaseException as error:
        error_type = type(error).__name__
        raise
    finally:
        safely(span.set_status, StatusCode.ERROR if error_type else StatusCode.OK)
        if error_type:
            safely(span.set_attribute, "error.type", error_type)
        safely(span.end)
        with recorder.lock:
            summary = recorder.stages.setdefault(name, StageSummary(name=name))
            summary.calls += 1
            summary.duration_ms += (perf_counter() - started) * 1000
            summary.failures += int(error_type is not None)
            summary.error_type = error_type or summary.error_type


def stage(name):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with measure(name):
                return function(*args, **kwargs)

        return wrapped

    return decorate


@contextmanager
def provider_call(provider: str, operation: str, **metadata):
    call = ProviderCall(provider=provider, operation=operation, **metadata)
    started = perf_counter()
    span_name = (
        "llm.invoke"
        if provider == "openai" and "embedding" not in operation
        else ("embeddings.invoke" if provider == "openai" else f"tavily.{operation}")
    )
    try:
        with measure(span_name, client=True) as span:
            try:
                yield call
            except BaseException as error:
                call.status = "failed"
                call.error_type = type(error).__name__
                raise
            finally:
                attrs = (
                    gen_ai_attributes(call)
                    if provider == "openai"
                    else {
                        "auron.provider.name": provider,
                        "auron.provider.operation": operation,
                    }
                )
                for key in (
                    "retry_count",
                    "batch_count",
                    "embedded_units",
                    "search_depth",
                    "query_count",
                    "candidates",
                    "search_mode",
                    "extract_depth",
                    "successful_extractions",
                    "failed_extractions",
                ):
                    value = getattr(call, key)
                    if value is not None:
                        attrs[f"auron.provider.{key}"] = value
                safely(span.set_attributes, attrs)
    finally:
        call.duration_ms = (perf_counter() - started) * 1000
        recorder = _current.get()
        if recorder is not None:
            with recorder.lock:
                recorder.calls.append(call)


class UsageCallback(BaseCallbackHandler):
    def __init__(self, call):
        self.call = call

    def on_llm_end(self, response, **kwargs):
        try:
            for generations in response.generations:
                for generation in generations:
                    message = getattr(generation, "message", None)
                    usage = getattr(message, "usage_metadata", None)
                    if usage:
                        self.call.input_tokens = usage.get("input_tokens")
                        self.call.output_tokens = usage.get("output_tokens")
                        self.call.cached_input_tokens = usage.get("input_token_details", {}).get(
                            "cache_read"
                        )
        except Exception:
            logger.warning("Model usage metadata unavailable")

    def on_retry(self, retry_state, **kwargs):
        self.call.retry_count = (self.call.retry_count or 0) + 1


def invoke_llm(model, messages, operation, *, model_name):
    if _current.get() is None:
        return model.invoke(messages)
    # Structured runnable wraps the chat model, so its model name is supplied by the caller.
    with provider_call("openai", operation, model=model_name) as call:
        return model.invoke(messages, config={"callbacks": [UsageCallback(call)]})


@contextmanager
def embedding_operation(name):
    token = _embedding_operation.set(name)
    try:
        yield
    finally:
        _embedding_operation.reset(token)


class EmbeddingClientTelemetry:
    """Observe actual SDK batches without altering LangChain's tokenization/batching."""

    def __init__(self, client, model):
        self.client = client
        self.model = model

    def __getattr__(self, name):
        return getattr(self.client, name)

    def create(self, *args, **kwargs):
        if _current.get() is None:
            return self.client.create(*args, **kwargs)
        inputs = kwargs.get("input", [])
        units = len(inputs) if isinstance(inputs, list) else 1
        stat(add=True, embedding_provider_batches=1, embedded_units=units)
        with provider_call(
            "openai",
            _embedding_operation.get(),
            model=self.model,
            batch_count=1,
            embedded_units=units,
        ) as call:
            response = self.client.create(*args, **kwargs)
            try:
                usage = (
                    response.get("usage")
                    if isinstance(response, dict)
                    else getattr(response, "usage", None)
                )
                if usage:
                    call.input_tokens = (
                        usage.get("prompt_tokens")
                        if isinstance(usage, dict)
                        else getattr(usage, "prompt_tokens", None)
                    )
            except Exception:
                logger.warning("Embedding usage metadata unavailable")
            return response
