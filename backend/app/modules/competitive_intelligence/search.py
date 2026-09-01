from typing import Any

import httpx

from .errors import SearchProviderError

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class TavilySearchClient:
    def __init__(self, *, api_key: str, timeout_seconds: float = 60.0) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def search(self, question: str) -> str | None:
        try:
            response = httpx.post(
                TAVILY_SEARCH_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "query": question,
                    "search_depth": "advanced",
                    "max_results": 2,
                    "include_answer": True,
                    "include_raw_content": True,
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload: Any = response.json()
        except (httpx.HTTPError, TypeError, ValueError) as error:
            raise SearchProviderError("Tavily search failed") from error

        if not isinstance(payload, dict):
            raise SearchProviderError("Tavily returned an invalid response")
        answer = payload.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            return None
        return answer.strip()
