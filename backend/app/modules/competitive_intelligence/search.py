from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from .errors import SearchProviderError

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


@dataclass(frozen=True, slots=True)
class SearchSource:
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    answer: str | None
    sources: tuple[SearchSource, ...]


class TavilySearchClient:
    def __init__(self, *, api_key: str, timeout_seconds: float = 60.0) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def search(self, question: str) -> SearchResult:
        try:
            response = httpx.post(
                TAVILY_SEARCH_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "query": question,
                    "search_depth": "advanced",
                    "max_results": 2,
                    "include_answer": True,
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload: Any = response.json()
        except (httpx.HTTPError, TypeError, ValueError) as error:
            raise SearchProviderError("Tavily search failed") from error

        if not isinstance(payload, dict):
            raise SearchProviderError("Tavily returned an invalid response")

        raw_answer = payload.get("answer")
        raw_results = payload.get("results")
        if raw_answer is not None and not isinstance(raw_answer, str):
            raise SearchProviderError("Tavily returned an invalid response")
        if not isinstance(raw_results, list):
            raise SearchProviderError("Tavily returned an invalid response")

        answer = raw_answer.strip() if raw_answer and raw_answer.strip() else None
        sources: list[SearchSource] = []
        for raw_result in raw_results:
            if not isinstance(raw_result, dict):
                continue
            raw_title = raw_result.get("title")
            raw_url = raw_result.get("url")
            if not isinstance(raw_title, str) or not isinstance(raw_url, str):
                continue

            title = raw_title.strip()
            url = raw_url.strip()
            if not title or not _is_valid_source_url(url):
                continue
            sources.append(SearchSource(title=title, url=url))

        return SearchResult(answer=answer, sources=tuple(sources))


def _is_valid_source_url(url: str) -> bool:
    if any(character.isspace() or ord(character) < 32 for character in url):
        return False
    try:
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname
        parsed_url.port
        if hostname is not None:
            hostname.encode("idna")
    except (UnicodeError, ValueError):
        return False
    return (
        parsed_url.scheme.lower() in {"http", "https"}
        and hostname is not None
        and bool(hostname)
        and parsed_url.username is None
        and parsed_url.password is None
    )
