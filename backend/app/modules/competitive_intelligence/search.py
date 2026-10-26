from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from .errors import SearchProviderError
from .evidence import SourceDocument
from .telemetry import provider_call, safe_url, stage, stat

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"

SEARCH_CANDIDATES = 10
PRIMARY_CANDIDATES = 5
TARGET_DOCUMENTS = 3
EXTRACT_RETRY_ATTEMPTS = 1


@dataclass(frozen=True, slots=True)
class SearchSource:
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    sources: tuple[SearchSource, ...]
    documents: tuple[SourceDocument, ...] = ()


class TavilySearchClient:
    def __init__(self, *, api_key: str, timeout_seconds: float = 60.0) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def search(self, question: str) -> SearchResult:
        with provider_call(
            "tavily",
            "search",
            search_depth="advanced",
            search_mode="general",
            query_count=1,
            retry_count=0,
        ) as call:
            raw_results = self._request(
                TAVILY_SEARCH_URL,
                {
                    "query": question,
                    "search_depth": "advanced",
                    "max_results": SEARCH_CANDIDATES,
                    "include_answer": False,
                    "include_raw_content": True,
                    "include_published_date": True,
                    "include_usage": True,
                },
                call,
            )
            call.candidates = len(raw_results)
            stat(add=True, source_candidates=len(raw_results))

        source_documents: list[SourceDocument] = []

        for provider_rank, raw_result in enumerate(
            raw_results,
            start=1,
        ):
            if not isinstance(raw_result, dict):
                continue

            document = create_source_document(
                research_query=question,
                result=raw_result,
                provider_rank=provider_rank,
            )

            if document is None:
                continue

            source_documents.append(document)

        selected_documents = self._select_documents(source_documents)
        call.documents_selected = len(selected_documents)

        selected_sources = [
            SearchSource(
                title=document.title,
                url=str(document.url),
            )
            for document in selected_documents
        ]

        return SearchResult(
            sources=tuple(selected_sources),
            documents=tuple(selected_documents),
        )

    def _request(self, url, body, call) -> list:
        try:
            response = httpx.post(
                url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload: Any = response.json()
        except (httpx.HTTPError, TypeError, ValueError) as error:
            raise SearchProviderError(f"Tavily {call.operation} failed") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise SearchProviderError("Tavily returned an invalid response")
        usage = payload.get("usage")
        if isinstance(usage, dict):
            credits = usage.get("credits")
            # Provider usage is optional; malformed usage must not invalidate sources.
            if isinstance(credits, (int, float)) and not isinstance(credits, bool):
                value = Decimal(str(credits))
                if value.is_finite() and value >= 0:
                    call.usage_credits = value
        return payload["results"]

    def _extract_raw_content(
        self,
        documents: list[SourceDocument],
    ) -> dict[str, str]:
        pending_urls = [str(document.url) for document in documents if document.raw_content is None]

        if not pending_urls:
            return {}

        extracted_by_url: dict[str, str] = {}

        for attempt in range(EXTRACT_RETRY_ATTEMPTS + 1):
            if not pending_urls:
                break

            with provider_call(
                "tavily",
                "extract",
                extract_depth="advanced",
                retry_count=attempt,
                extraction_urls=[safe_url(url) for url in pending_urls],
            ) as call:
                raw_results = self._request(
                    TAVILY_EXTRACT_URL,
                    {
                        "urls": pending_urls,
                        "extract_depth": "advanced",
                        "format": "markdown",
                        "include_usage": True,
                    },
                    call,
                )

                successful_urls: set[str] = set()

                for raw_result in raw_results:
                    if not isinstance(raw_result, dict):
                        continue

                    raw_url = raw_result.get("url")
                    raw_content = raw_result.get("raw_content")

                    if not isinstance(raw_url, str):
                        continue

                    if not isinstance(raw_content, str):
                        continue

                    url = raw_url.strip()
                    content = raw_content.strip()

                    if not url or not content or url not in pending_urls:
                        continue

                    extracted_by_url[url] = content
                    successful_urls.add(url)

                pending_urls = [url for url in pending_urls if url not in successful_urls]
                call.successful_extractions = len(successful_urls)
                call.failed_extractions = len(pending_urls)

        return extracted_by_url

    @stage("source_acquisition")
    def _acquire_raw_content(
        self,
        documents: list[SourceDocument],
    ) -> list[SourceDocument]:
        missing_raw = [document for document in documents if document.raw_content is None]

        if not missing_raw:
            return documents

        extracted_by_url = self._extract_raw_content(missing_raw)

        updated_documents: list[SourceDocument] = []

        for document in documents:
            extracted_content = extracted_by_url.get(str(document.url))

            if extracted_content is not None:
                document = document.model_copy(
                    update={
                        "raw_content": extracted_content,
                        "content_source": "extract_raw",
                    }
                )

            updated_documents.append(document)

        return updated_documents

    def _select_documents(
        self,
        candidates: list[SourceDocument],
    ) -> list[SourceDocument]:
        primary_candidates = candidates[:PRIMARY_CANDIDATES]

        primary_candidates = self._acquire_raw_content(primary_candidates)

        full_documents = [
            document for document in primary_candidates if document.raw_content is not None
        ]

        if len(full_documents) >= TARGET_DOCUMENTS:
            return full_documents[:TARGET_DOCUMENTS]

        secondary_candidates = candidates[PRIMARY_CANDIDATES:]

        secondary_candidates = self._acquire_raw_content(secondary_candidates)

        all_candidates = primary_candidates + secondary_candidates

        full_documents = [
            document for document in all_candidates if document.raw_content is not None
        ]

        if len(full_documents) >= TARGET_DOCUMENTS:
            return full_documents[:TARGET_DOCUMENTS]

        return self._fill_with_search_content(
            candidates=all_candidates,
            selected=full_documents,
        )

    def _fill_with_search_content(
        self,
        *,
        candidates: list[SourceDocument],
        selected: list[SourceDocument],
    ) -> list[SourceDocument]:
        selected_documents = selected[:TARGET_DOCUMENTS]

        remaining = TARGET_DOCUMENTS - len(selected_documents)

        if remaining <= 0:
            return selected_documents

        selected_ids = {document.source_id for document in selected_documents}

        fallback_candidates = [
            document
            for document in candidates
            if (document.source_id not in selected_ids and document.content)
        ]

        for document in fallback_candidates[:remaining]:
            selected_documents.append(
                document.model_copy(
                    update={
                        "content_source": "search_content",
                    }
                )
            )

        return selected_documents


def _is_valid_source_url(url: str) -> bool:
    if any(character.isspace() or ord(character) < 32 for character in url):
        return False
    try:
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname
        parsed_url.port
        if hostname is not None:
            hostname.encode("idna")
    except UnicodeError, ValueError:
        return False
    return (
        parsed_url.scheme.lower() in {"http", "https"}
        and hostname is not None
        and bool(hostname)
        and parsed_url.username is None
        and parsed_url.password is None
    )


def create_source_document(
    *,
    research_query: str,
    result: dict[str, Any],
    provider_rank: int,
) -> SourceDocument | None:
    raw_title = result.get("title")
    raw_url = result.get("url")
    raw_content_summary = result.get("content")
    raw_content = result.get("raw_content")
    raw_score = result.get("score")
    raw_provider_id = result.get("id")

    if not isinstance(raw_title, str):
        return None

    if not isinstance(raw_url, str):
        return None

    if not isinstance(raw_content_summary, str):
        return None

    title = raw_title.strip()
    url = raw_url.strip()
    content = raw_content_summary.strip()

    if not title or not content or not _is_valid_source_url(url):
        return None

    parsed_url = urlparse(url)
    domain = parsed_url.hostname

    if domain is None:
        return None

    if isinstance(raw_content, str):
        raw_content = raw_content.strip() or None
    else:
        raw_content = None

    provider_score = (
        float(raw_score)
        if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool)
        else None
    )

    provider_result_id = (
        raw_provider_id.strip()
        if isinstance(raw_provider_id, str) and raw_provider_id.strip()
        else None
    )

    content_source = "search_raw" if raw_content is not None else "search_content"

    published_date = _parse_published_date(result.get("published_date"))

    return SourceDocument(
        source_id=f"src_{uuid4().hex}",
        provider_result_id=provider_result_id,
        research_query=research_query.strip(),
        title=title,
        url=url,
        domain=domain.lower(),
        content=content,
        raw_content=raw_content,
        provider_score=provider_score,
        provider_rank=provider_rank,
        content_source=content_source,
        published_date=published_date,
        retrieved_at=datetime.now(UTC),
    )


def _parse_published_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = parsedate_to_datetime(value)
    except TypeError, ValueError:
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)

    return parsed
