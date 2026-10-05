from dataclasses import dataclass
from uuid import UUID, uuid4

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from .context_builder import build_research_context
from .document_processing import chunk_document
from .embeddings import get_embeddings
from .errors import NoSearchResultsError, VectorStoreError
from .evidence import EvidenceChunk, RetrievedEvidence, SourceDocument

RETRIEVAL_LIMIT = 5
INDEX_BATCH_SIZE = 1000
COLLECTION_NAME_PREFIX = "competitive_intelligence"


def create_vector_store(
    *, collection_name: str | None = None, embeddings: OpenAIEmbeddings | None = None,
) -> Chroma:
    """Create a disposable Chroma collection isolated from every other run."""

    client = chromadb.EphemeralClient()
    resolved_name = collection_name or f"{COLLECTION_NAME_PREFIX}_{uuid4().hex}"
    return Chroma(
        client=client,
        collection_name=resolved_name,
        embedding_function=embeddings if embeddings is not None else get_embeddings(),
        collection_configuration={
            "hnsw": {
                "space": "cosine",
            }
        },
    )


def index_chunks(
    vector_store: Chroma,
    chunks: list[EvidenceChunk],
) -> None:
    documents = []

    ids = []

    for chunk in chunks:
        documents.append(
            Document(
                page_content=chunk.text,
                metadata={
                    "chunk_id": chunk.chunk_id,
                    "source_id": chunk.source_id,
                    "research_query": chunk.research_query,
                    "chunk_index": chunk.chunk_index,
                    "token_count": chunk.token_count,
                },
            )
        )

        ids.append(chunk.chunk_id)

    for start in range(0, len(documents), INDEX_BATCH_SIZE):
        vector_store.add_documents(
            documents=documents[start : start + INDEX_BATCH_SIZE],
            ids=ids[start : start + INDEX_BATCH_SIZE],
        )


def retrieve_evidence(
    vector_store: Chroma,
    query: str,
    *,
    top_k: int = RETRIEVAL_LIMIT,
    query_embedding: list[float] | None = None,
    sources: list[SourceDocument] | None = None,
) -> list[RetrievedEvidence]:
    if query_embedding is None:
        results = vector_store.similarity_search_with_score(query=query, k=top_k)
    else:
        results = vector_store.similarity_search_by_vector_with_relevance_scores(
            embedding=query_embedding, k=top_k,
        )
    source_by_id = {source.source_id: source for source in sources or []}

    retrieved: list[RetrievedEvidence] = []

    for rank, (document, distance) in enumerate(
        results,
        start=1,
    ):
        retrieved.append(
            RetrievedEvidence(
                chunk_id=document.metadata["chunk_id"],
                source_id=document.metadata["source_id"],
                text=document.page_content,
                query=query,
                distance=distance,
                rank=rank,
                source=source_by_id.get(document.metadata["source_id"]),
            )
        )

    return retrieved


@dataclass(frozen=True, slots=True)
class ContextRetrievalResult:
    context: str
    documents_indexed: int
    embedding_units_indexed: int
    embedding_units_retrieved: int


class ChromaEvidenceStore:
    """Production lifecycle around the same V2 functions used by the benchmark."""

    def __init__(self, *, api_key: str, base_url: str | None) -> None:
        self._embeddings = get_embeddings(api_key=api_key, base_url=base_url)

    def index_and_retrieve(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        questions: list[str],
        documents: list[SourceDocument],
    ) -> ContextRetrievalResult:
        chunks = [chunk for document in documents for chunk in chunk_document(document)]
        if not chunks:
            raise NoSearchResultsError("No valid source chunks were produced")

        vector_store = None
        try:
            vector_store = create_vector_store(
                collection_name=f"ci_{organization_id.hex}_{execution_id.hex}",
                embeddings=self._embeddings,
            )
            index_chunks(vector_store, chunks)
            retrieved: list[RetrievedEvidence] = []
            seen_chunks: set[str] = set()
            for question in questions:
                for evidence in retrieve_evidence(
                    vector_store, question, top_k=RETRIEVAL_LIMIT, sources=documents,
                ):
                    if evidence.chunk_id not in seen_chunks:
                        seen_chunks.add(evidence.chunk_id)
                        retrieved.append(evidence)
            if not retrieved:
                raise NoSearchResultsError("No source evidence was retrieved")
            return ContextRetrievalResult(
                context=build_research_context(retrieved, documents),
                documents_indexed=len({chunk.source_id for chunk in chunks}),
                embedding_units_indexed=len(chunks),
                embedding_units_retrieved=len(retrieved),
            )
        except NoSearchResultsError:
            raise
        except Exception as error:
            raise VectorStoreError("Chroma indexing or retrieval failed") from error
        finally:
            if vector_store is not None:
                try:
                    vector_store.delete_collection()
                except Exception:
                    pass
