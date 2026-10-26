from functools import lru_cache

from langchain_openai import OpenAIEmbeddings

from .evidence import EvidenceChunk
from .telemetry import EmbeddingClientTelemetry

EMBEDDING_MODEL_NAME = "text-embedding-3-small"


@lru_cache(maxsize=1)
def get_embeddings(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> OpenAIEmbeddings:
    embeddings = OpenAIEmbeddings(
        model=EMBEDDING_MODEL_NAME,
        api_key=api_key,
        base_url=base_url,
    )
    embeddings.client = EmbeddingClientTelemetry(embeddings.client, embeddings.model)
    return embeddings


def embed_chunk(chunk: EvidenceChunk) -> list[float]:
    embeddings = get_embeddings()

    vectors = embeddings.embed_documents([chunk.text])

    return vectors[0]


def embed_chunks(
    chunks: list[EvidenceChunk],
) -> list[list[float]]:
    embeddings = get_embeddings()

    texts = [chunk.text for chunk in chunks]

    return embeddings.embed_documents(texts)


def embed_query(query: str) -> list[float]:
    embeddings = get_embeddings()

    return embeddings.embed_query(query)
