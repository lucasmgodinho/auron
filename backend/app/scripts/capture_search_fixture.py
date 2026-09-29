"""
Captures a live search result and stores the normalized SourceDocument objects
as a frozen evaluation fixture.

Flow:

Research question
→ Tavily live search
→ SourceDocument[]
→ JSON fixture

This script exists only for development and evaluation purposes.

The Competitive Intelligence production pipeline must continue using Tavily
in real time. The fixture created by this script allows evaluation runs to use
exactly the same source documents across multiple experiments.

Freezing SourceDocument objects instead of Tavily's raw response preserves the
search provider abstraction while still allowing downstream pipeline components
to be changed and evaluated independently.

Those downstream components include:

- structural normalization;
- chunking;
- embeddings;
- vector indexing;
- retrieval;
- context construction;
- report generation;
- evaluation.

Run this script only when an evaluation fixture should be created or explicitly
refreshed.

Run from:

    C:\\Auron\\backend

With:

    python -m app.scripts.capture_search_fixture

IMPORTANT:
Each execution performs a real Tavily request and consumes Tavily credits.

Refreshing a fixture changes the evaluation input dataset and may make results
from previous experiments no longer directly comparable.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from app.modules.competitive_intelligence.search import (
    TavilySearchClient,
)
from app.scripts.search_fixture import (
    save_search_fixture,
)

RESEARCH_QUESTION = "Who are Microsoft's main competitors in the technology sector?"

FIXTURE_FILENAME = "microsoft_competitors.json"


def load_environment() -> str:
    project_root = Path(__file__).resolve().parents[3]
    env_file = project_root / ".env"

    if not env_file.exists():
        raise RuntimeError(f".env file was not found at: {env_file}")

    load_dotenv(env_file)

    tavily_api_key = os.getenv("TAVILY_API_KEY")

    if not tavily_api_key:
        raise RuntimeError("TAVILY_API_KEY was not found.")

    return tavily_api_key


def main() -> None:
    tavily_api_key = load_environment()

    client = TavilySearchClient(
        api_key=tavily_api_key,
    )

    print("Searching Tavily...")
    print(RESEARCH_QUESTION)

    result = client.search(RESEARCH_QUESTION)

    if not result.documents:
        raise RuntimeError("Tavily returned no SourceDocuments.")

    path = save_search_fixture(
        filename=FIXTURE_FILENAME,
        research_question=RESEARCH_QUESTION,
        documents=list(result.documents),
    )

    print()
    print(f"Saved {len(result.documents)} SourceDocuments.")
    print(f"Fixture: {path}")


if __name__ == "__main__":
    main()
