"""
Inspect all retrieval candidates from a frozen search fixture.

The script exists to support manual relevance labeling for retrieval
evaluation.

Flow:

Frozen SourceDocument[]
→ document processing
→ chunking
→ inspect every candidate chunk

No Tavily, OpenAI, embeddings, Chroma, or LLM calls are performed.

Relevance labels should use:

2 = highly relevant
1 = partially relevant
0 = irrelevant

Run from:

    C:\\Auron\\backend

With:

    python -m app.scripts.inspect_retrieval_candidates
"""

from app.modules.competitive_intelligence.document_processing import (
    chunk_document,
)
from app.scripts.search_fixture import (
    load_search_fixture,
)

RESEARCH_QUESTION = "Who are Microsoft's main competitors in the technology sector?"

FIXTURE_FILENAME = "microsoft_competitors.json"

PREVIEW_CHARS = 1200


def compact_text(
    text: str,
    *,
    max_length: int,
) -> str:
    normalized = " ".join(text.split())

    if len(normalized) <= max_length:
        return normalized

    return normalized[: max_length - 3] + "..."


def main() -> None:
    fixture = load_search_fixture(
        filename=FIXTURE_FILENAME,
        expected_question=RESEARCH_QUESTION,
    )

    documents = list(fixture.documents)

    print("=" * 80)
    print("RETRIEVAL CANDIDATE INSPECTION")
    print("=" * 80)

    print()
    print(f"Question: {RESEARCH_QUESTION}")

    print(f"Documents: {len(documents)}")

    all_chunks = []

    for document in documents:
        document_chunks = chunk_document(document)

        for chunk in document_chunks:
            all_chunks.append(
                (
                    document,
                    chunk,
                )
            )

    print(f"Candidate chunks: {len(all_chunks)}")

    for candidate_index, (
        document,
        chunk,
    ) in enumerate(
        all_chunks,
        start=1,
    ):
        print()
        print("=" * 80)

        print(f"CANDIDATE {candidate_index}/{len(all_chunks)}")

        print(f"Chunk ID: {chunk.chunk_id}")

        print(f"Chunk index: {chunk.chunk_index}")

        print(f"Tokens: {chunk.token_count}")

        print(f"Source rank: {document.provider_rank}")

        print(f"Source score: {document.provider_score}")

        print(f"Title: {document.title}")

        print(f"URL: {document.url}")

        print()
        print("CONTENT")
        print("-" * 80)

        print(
            compact_text(
                chunk.text,
                max_length=PREVIEW_CHARS,
            )
        )

        print()
        print("Relevance: [0 / 1 / 2]")


if __name__ == "__main__":
    main()
