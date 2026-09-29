"""
Manual experiment for validating semantic retrieval with Chroma.

Flow:

SourceDocument[]
→ structural normalization
→ token-based chunking
→ EvidenceChunk[]
→ OpenAI embeddings
→ Chroma indexing
→ cosine similarity search
→ RetrievedEvidence[]

This script exists for development and evaluation purposes.

Its goal is to validate that Chroma produces semantically coherent retrieval
results and to compare its ranking behavior with the manual cosine similarity
baseline implemented in inspect_document_processing.py.

The vector store is intentionally isolated from the production workflow so
retrieval behavior can be inspected independently.

It is not part of the Competitive Intelligence production pipeline.

Run from:

    C:\\Auron\\backend

With:

    python -m app.scripts.inspect_chroma_retrieval

IMPORTANT:
This script performs real OpenAI embedding requests and may consume API credits.

If the script still performs a live Tavily search, it will also consume Tavily
credits. Prefer frozen SourceDocument fixtures for repeatable evaluation runs.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

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
PREVIEW_LENGTH = 500


def load_environment() -> str:
    project_root = Path(__file__).resolve().parents[3]
    env_file = project_root / ".env"

    if not env_file.exists():
        raise RuntimeError(f".env file was not found at: {env_file}")

    load_dotenv(env_file)

    tavily_api_key = os.getenv("TAVILY_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if not tavily_api_key:
        raise RuntimeError("TAVILY_API_KEY was not found.")

    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY was not found.")

    return tavily_api_key


def main() -> None:
    tavily_api_key = load_environment()

    client = TavilySearchClient(
        api_key=tavily_api_key,
    )

    print("=" * 80)
    print("COMPETITIVE INTELLIGENCE - CHROMA RETRIEVAL")
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

    for index, document in enumerate(
        result.documents,
        start=1,
    ):
        chunks = chunk_document(document)

        all_chunks.extend(chunks)

        print()
        print(f"Source {index}:")
        print(document.title)
        print(f"Chunks generated: {len(chunks)}")

    if not all_chunks:
        print("No chunks were generated.")
        return

    print()
    print(f"Total chunks: {len(all_chunks)}")

    print()
    print("-" * 80)
    print("CREATING CHROMA COLLECTION")
    print("-" * 80)

    vector_store = create_vector_store()

    print()
    print("Indexing chunks...")

    index_chunks(
        vector_store,
        all_chunks,
    )

    print(f"Indexed chunks: {len(all_chunks)}")

    print()
    print("-" * 80)
    print("CHROMA SIMILARITY SEARCH")
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
        print("=" * 80)
        print(f"RANK {evidence.rank}")
        print("=" * 80)

        print(f"Distance: {evidence.distance:.6f}")
        print(f"Chunk ID: {evidence.chunk_id}")
        print(f"Source ID: {evidence.source_id}")

        print()
        print("Preview:")
        print(evidence.text[:PREVIEW_LENGTH])


if __name__ == "__main__":
    main()
