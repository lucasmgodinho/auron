from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID, uuid4

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from .embeddings import get_embeddings
from .errors import NoSearchResultsError, VectorStoreError
from .evidence import EvidenceChunk, RetrievedEvidence

EMBEDDING_MODEL_NAME = "text-embedding-3-small"
RETRIEVAL_LIMIT = 10
COLLECTION_NAME_PREFIX = "competitive_intelligence"


def create_vector_store(*, collection_name: str | None = None) -> Chroma:
    """Create a disposable Chroma collection isolated from every other run."""

    client = chromadb.EphemeralClient()
    resolved_name = collection_name or f"{COLLECTION_NAME_PREFIX}_{uuid4().hex}"
    return Chroma(
        client=client,
        collection_name=resolved_name,
        embedding_function=get_embeddings(),
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

    vector_store.add_documents(
        documents=documents,
        ids=ids,
    )


def retrieve_evidence(
    vector_store: Chroma,
    query: str,
    *,
    top_k: int = 5,
) -> list[RetrievedEvidence]:
    results = vector_store.similarity_search_with_score(
        query=query,
        k=top_k,
    )

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
            )
        )

    return retrieved


@dataclass(frozen=True, slots=True)
class ContextRetrievalResult:
    context: str
    documents_indexed: int
    embedding_units_indexed: int
    embedding_units_retrieved: int


class ChromaContextStore:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        embedding_model: str = EMBEDDING_MODEL_NAME,
    ) -> None:
        self._embeddings = OpenAIEmbeddings(
            model=embedding_model,
            api_key=api_key,
            base_url=base_url,
        )

    def index_and_retrieve(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        company_name: str,
        documents: Sequence[Mapping[str, str]],
    ) -> ContextRetrievalResult:
        valid_documents = [document for document in documents if document.get("answer", "").strip()]
        if not valid_documents:
            raise NoSearchResultsError("No valid search documents were produced")

        client = chromadb.EphemeralClient()
        collection_name = f"ci_{execution_id.hex}"
        collection_created = False
        try:
            collection = client.create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            collection_created = True
            answers = [document["answer"].strip() for document in valid_documents]
            embeddings = self._embeddings.embed_documents(answers)
            collection.add(
                ids=[
                    f"{organization_id.hex}:{execution_id.hex}:{index}"
                    for index in range(len(answers))
                ],
                embeddings=embeddings,
                documents=answers,
                metadatas=[
                    {
                        "organization_id": str(organization_id),
                        "execution_id": str(execution_id),
                        "question": document["question"],
                    }
                    for document in valid_documents
                ],
            )
            if collection.count() == 0:
                raise NoSearchResultsError("No search documents were indexed")

            query_embedding = self._embeddings.embed_query(
                f"Competitive analysis data for {company_name}"
            )
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(RETRIEVAL_LIMIT, len(answers)),
                include=["documents"],
            )
            result_batches = results.get("documents") or []
            retrieved = [
                document.strip()
                for batch in result_batches
                for document in batch
                if isinstance(document, str) and document.strip()
            ]
            if not retrieved:
                raise NoSearchResultsError("No search documents were retrieved")

            return ContextRetrievalResult(
                context="\n\n".join(retrieved),
                documents_indexed=len(valid_documents),
                embedding_units_indexed=len(answers),
                embedding_units_retrieved=len(retrieved),
            )

        except NoSearchResultsError:
            raise
        except Exception as error:
            raise VectorStoreError("Chroma indexing or retrieval failed") from error
        finally:
            if collection_created:
                try:
                    client.delete_collection(collection_name)
                except Exception:
                    pass
