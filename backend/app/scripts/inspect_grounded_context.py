"""
Manual experiment for validating grounded context construction.

Flow:

SourceDocument[]
→ structural normalization
→ token-based chunking
→ EvidenceChunk[]
→ embeddings
→ Chroma
→ RetrievedEvidence[]
→ grounded research context

This script exists for development and evaluation purposes.

Its goal is to verify the provenance chain between retrieved evidence and its
original SourceDocument before any report generation occurs.

The resulting context should contain only the information required by the
generation model, including stable evidence identifiers such as E1, E2, and E3,
along with source metadata and retrieved content.

This allows evidence lineage and context quality to be inspected independently
from the LLM generation step.

It is not part of the Competitive Intelligence production pipeline.

Run from:

    C:\\Auron\\backend

With:

    python -m app.scripts.inspect_grounded_context

IMPORTANT:
This script may perform real OpenAI embedding requests.

For reproducible evaluation, prefer loading frozen SourceDocument fixtures
instead of performing a new live Tavily search.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from app.modules.competitive_intelligence.context_builder import (
    build_research_context,
)
from app.modules.competitive_intelligence.document_processing import (
    chunk_document,
)
from app.modules.competitive_intelligence.search import (
    TavilySearchClient,
)
from app.modules.competitive_intelligence.vector_store import (
    create_vector_store,
    index_chunks,
    retrieve_evidence,
)

RESEARCH_QUESTION = "Who are Microsoft's main competitors in the technology sector?"

TOP_K = 5


def load_environment() -> str:
    project_root = Path(__file__).resolve().parents[3]
    env_file = project_root / ".env"

    if not env_file.exists():
        raise RuntimeError(f".env file was not found at: {env_file}")

    load_dotenv(env_file)

    tavily_api_key = os.getenv("TAVILY_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if not tavily_api_key:
        raise RuntimeError("TAVILY_API_KEY was not found in the .env file.")

    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY was not found in the .env file.")

    return tavily_api_key


def main() -> None:
    tavily_api_key = load_environment()

    client = TavilySearchClient(
        api_key=tavily_api_key,
    )

    print("=" * 80)
    print("COMPETITIVE INTELLIGENCE - GROUNDED CONTEXT")
    print("=" * 80)

    print()
    print("Research query:")
    print(RESEARCH_QUESTION)

    print()
    print("Searching Tavily...")

    result = client.search(RESEARCH_QUESTION)

    print()
    print(f"SourceDocuments found: {len(result.documents)}")

    if not result.documents:
        print("No SourceDocument was created.")
        return

    all_chunks = []

    print()
    print("-" * 80)
    print("DOCUMENT PROCESSING")
    print("-" * 80)

    for index, document in enumerate(
        result.documents,
        start=1,
    ):
        chunks = chunk_document(document)

        all_chunks.extend(chunks)

        print()
        print(f"Source {index}:")
        print(document.title)
        print(f"Source ID: {document.source_id}")
        print(f"Domain: {document.domain}")
        print(f"Chunks generated: {len(chunks)}")

    if not all_chunks:
        print()
        print("No chunks were generated.")
        return

    print()
    print(f"Total chunks: {len(all_chunks)}")

    print()
    print("-" * 80)
    print("CHROMA INDEXING")
    print("-" * 80)

    vector_store = create_vector_store()

    index_chunks(
        vector_store,
        all_chunks,
    )

    print()
    print(f"Indexed chunks: {len(all_chunks)}")

    print()
    print("-" * 80)
    print("RETRIEVAL")
    print("-" * 80)

    retrieved = retrieve_evidence(
        vector_store,
        RESEARCH_QUESTION,
        top_k=TOP_K,
    )

    print()
    print(f"Retrieved evidence: {len(retrieved)}")

    for evidence in retrieved:
        print()
        print(
            f"Rank {evidence.rank} | Distance {evidence.distance:.6f} | Chunk {evidence.chunk_id}"
        )

    print()
    print("-" * 80)
    print("BUILDING GROUNDED CONTEXT")
    print("-" * 80)

    context = build_research_context(
        retrieved=retrieved,
        sources=list(result.documents),
    )

    print()
    print("=" * 80)
    print("GROUNDED CONTEXT")
    print("=" * 80)
    print()
    print(context)

    print()
    print("=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)

    print()
    print(f"Sources available: {len(result.documents)}")
    print(f"Chunks indexed: {len(all_chunks)}")
    print(f"Evidence retrieved: {len(retrieved)}")
    print(f"Context characters: {len(context)}")


if __name__ == "__main__":
    main()
