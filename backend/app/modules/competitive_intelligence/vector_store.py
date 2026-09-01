from collections.abc import Mapping, Sequence
from uuid import UUID

import chromadb
from langchain_openai import OpenAIEmbeddings

from .errors import NoSearchResultsError, VectorStoreError

EMBEDDING_MODEL_NAME = "text-embedding-3-small"
RETRIEVAL_LIMIT = 10


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
    ) -> str:
        valid_documents = [
            document
            for document in documents
            if document.get("answer", "").strip()
        ]
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
            return "\n\n".join(retrieved)
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
