"""
Manual experiment for validating Tavily raw content recovery.

Flow:

Frozen SourceDocument[]
→ select documents without raw_content
→ Tavily Extract Advanced
→ recovered raw_content

This script exists only for development and evaluation purposes.

Its goal is to validate whether Tavily Extract can recover full document
content for search results where Search returned raw_content=None.

The script intentionally uses a frozen search fixture so no new Tavily
Search request is performed and the same candidate URLs are preserved.

Run from:

    C:\\Auron\\backend

With:

    python -m app.scripts.inspect_tavily_extract

IMPORTANT:
This script performs real Tavily Extract requests and consumes Tavily credits.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from app.modules.competitive_intelligence.search import (
    TavilySearchClient,
)
from app.scripts.search_fixture import (
    load_search_fixture,
)

RESEARCH_QUESTION = "Who are Microsoft's main competitors in the technology sector?"

FIXTURE_FILENAME = "microsoft_competitors.json"


def load_environment() -> str:
    project_root = Path(__file__).resolve().parents[3]
    env_file = project_root / ".env"

    if not env_file.exists():
        raise RuntimeError(f".env file was not found at: {env_file}")

    load_dotenv(env_file)

    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key:
        raise RuntimeError("TAVILY_API_KEY was not found.")

    return api_key


def main() -> None:
    api_key = load_environment()

    fixture = load_search_fixture(
        filename=FIXTURE_FILENAME,
        expected_question=RESEARCH_QUESTION,
    )

    missing_raw = [document for document in fixture.documents if document.raw_content is None]

    print("=" * 80)
    print("TAVILY EXTRACT INSPECTION")
    print("=" * 80)

    print()
    print(f"Documents without raw_content: {len(missing_raw)}")

    for document in missing_raw:
        print()
        print(f"Rank {document.provider_rank} | Score {document.provider_score} | {document.title}")
        print(document.url)

    if not missing_raw:
        print()
        print("No extraction is required.")
        return

    client = TavilySearchClient(
        api_key=api_key,
    )

    extracted_by_url = client._extract_raw_content(missing_raw)

    print()
    print("-" * 80)
    print("EXTRACTION RESULTS")
    print("-" * 80)

    for document in missing_raw:
        url = str(document.url)
        extracted_content = extracted_by_url.get(url)

        print()
        print(f"Rank {document.provider_rank} | {document.title}")

        if extracted_content:
            print("Status: SUCCESS")
            print(f"Characters: {len(extracted_content)}")

            preview = extracted_content[:500]

            print()
            print("Preview:")
            print(preview)
        else:
            print("Status: FAILED")
    
    search_terms = [
        "Microsoft",
        "competitor",
        "Apple",
        "Google",
    ]

    print()
    print("Relevant term positions:")

    for term in search_terms:
        position = extracted_content.lower().find(
            term.lower()
        )

        print(
            f"{term}: "
            f"{position}"
        )
    
    position = extracted_content.lower().find(
        "microsoft"
    )

    if position >= 0:
        start = max(
            0,
            position - 500,
        )

        end = min(
            len(extracted_content),
            position + 2000,
        )

        print()
        print("Relevant content preview:")
        print(
            extracted_content[
                start:end
            ]
        )


if __name__ == "__main__":
    main()
