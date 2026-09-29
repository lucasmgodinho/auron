"""
Manual experiment for inspecting document processing and semantic retrieval
without using a vector database.

Flow:

Frozen or live SourceDocument[]
→ text selection
→ structural normalization
→ token-based chunking
→ EvidenceChunk[]
→ OpenAI embeddings
→ manual cosine similarity
→ ranked chunks

This script exists for development and learning purposes.

Its goal is to make the retrieval mechanics explicit before introducing
a vector store abstraction. It computes embeddings for the generated
chunks and the research query, then calculates cosine similarity manually
to inspect how semantic ranking behaves.

This script is useful as a reference baseline when validating vector store
retrieval behavior.

It is not part of the Competitive Intelligence production pipeline.

Run from:

    C:\\Auron\\backend

With:

    python -m app.scripts.inspect_document_processing

IMPORTANT:
This script may perform real OpenAI embedding requests and may consume API
credits depending on its current configuration.
"""

import math
import os
from pathlib import Path

from dotenv import load_dotenv

from app.modules.competitive_intelligence.document_processing import (
    chunk_document,
)
from app.modules.competitive_intelligence.embeddings import (
    embed_chunks,
    embed_query,
)
from app.modules.competitive_intelligence.search import (
    TavilySearchClient,
)

RESEARCH_QUESTION = "Who are Microsoft's main competitors in the technology sector?"

TOP_K = 5
BOTTOM_K = 3
PREVIEW_LENGTH = 500


def load_environment() -> str:
    """
    Load environment variables from the .env file
    located at the root of the Auron repository.
    """
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


def cosine_similarity(
    vector_a: list[float],
    vector_b: list[float],
) -> float:
    """
    Calculate cosine similarity between two vectors.
    """
    if len(vector_a) != len(vector_b):
        raise ValueError("Vectors must have the same dimensions.")

    dot_product = sum(a * b for a, b in zip(vector_a, vector_b))

    magnitude_a = math.sqrt(sum(value * value for value in vector_a))

    magnitude_b = math.sqrt(sum(value * value for value in vector_b))

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


def main() -> None:
    tavily_api_key = load_environment()

    client = TavilySearchClient(
        api_key=tavily_api_key,
    )

    print("=" * 80)
    print("COMPETITIVE INTELLIGENCE - RETRIEVAL EXPERIMENT")
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

    source_by_id = {document.source_id: document for document in result.documents}

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
    print("EMBEDDING CHUNKS")
    print("-" * 80)

    chunk_vectors = embed_chunks(all_chunks)

    print()
    print(f"Chunk embeddings generated: {len(chunk_vectors)}")

    print(f"Embedding dimensions: {len(chunk_vectors[0])}")

    print()
    print("-" * 80)
    print("EMBEDDING QUERY")
    print("-" * 80)

    query_vector = embed_query(RESEARCH_QUESTION)

    print()
    print(f"Query embedding dimensions: {len(query_vector)}")

    print()
    print("-" * 80)
    print("CALCULATING COSINE SIMILARITY")
    print("-" * 80)

    ranked_chunks = []

    for chunk, chunk_vector in zip(
        all_chunks,
        chunk_vectors,
    ):
        similarity = cosine_similarity(
            query_vector,
            chunk_vector,
        )

        ranked_chunks.append((similarity, chunk))

    ranked_chunks.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    print()
    print("=" * 80)
    print(f"TOP {TOP_K} MOST SIMILAR CHUNKS")
    print("=" * 80)

    for rank, (similarity, chunk) in enumerate(
        ranked_chunks[:TOP_K],
        start=1,
    ):
        source = source_by_id[chunk.source_id]

        print()
        print("-" * 80)
        print(f"RANK {rank}")
        print("-" * 80)

        print(f"Similarity: {similarity:.6f}")
        print(f"Source: {source.title}")
        print(f"Domain: {source.domain}")
        print(f"Chunk ID: {chunk.chunk_id}")
        print(f"Chunk index: {chunk.chunk_index}")
        print(f"Tokens: {chunk.token_count}")

        print()
        print("Preview:")
        print(chunk.text[:PREVIEW_LENGTH])

    print()
    print("=" * 80)
    print(f"BOTTOM {BOTTOM_K} LEAST SIMILAR CHUNKS")
    print("=" * 80)

    for similarity, chunk in ranked_chunks[-BOTTOM_K:]:
        source = source_by_id[chunk.source_id]

        print()
        print("-" * 80)

        print(f"Similarity: {similarity:.6f}")
        print(f"Source: {source.title}")
        print(f"Chunk index: {chunk.chunk_index}")

        print()
        print("Preview:")
        print(chunk.text[:PREVIEW_LENGTH])


if __name__ == "__main__":
    main()
