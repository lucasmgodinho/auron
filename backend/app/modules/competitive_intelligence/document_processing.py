import re

import tiktoken

from .evidence import EvidenceChunk, SourceDocument

EMBEDDING_MODEL = "text-embedding-3-small"

DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 64

TOKENIZER = tiktoken.encoding_for_model(EMBEDDING_MODEL)


def get_document_text(document: SourceDocument) -> str:
    if document.raw_content:
        return document.raw_content

    return document.content


def normalize_document_text(text: str) -> str:
    # Remove Markdown images.
    text = re.sub(
        r"!\[[^\]]*\]\([^)]+\)",
        "",
        text,
    )

    # Remove empty Markdown links.
    text = re.sub(
        r"\[\]\([^)]+\)",
        "",
        text,
    )

    # Preserve link text, remove destination URL.
    text = re.sub(
        r"\[([^\]]+)\]\([^)]+\)",
        r"\1",
        text,
    )

    # Remove trailing whitespace.
    text = "\n".join(line.rstrip() for line in text.splitlines())

    # Collapse excessive blank lines.
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


def chunk_document(
    document: SourceDocument,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[EvidenceChunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")

    if overlap < 0:
        raise ValueError("overlap cannot be negative")

    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    original_text = get_document_text(document)
    normalized_text = normalize_document_text(original_text)
    normalized_tokens = TOKENIZER.encode(normalized_text)

    chunks: list[EvidenceChunk] = []

    start = 0
    chunk_index = 0

    while start < len(normalized_tokens):
        end = min(
            start + chunk_size,
            len(normalized_tokens),
        )

        chunk_tokens = normalized_tokens[start:end]
        chunk_text = TOKENIZER.decode(chunk_tokens)

        chunks.append(
            EvidenceChunk(
                chunk_id=(f"{document.source_id}_chunk_{chunk_index}"),
                source_id=document.source_id,
                research_query=document.research_query,
                text=chunk_text,
                chunk_index=chunk_index,
                token_count=len(chunk_tokens),
            )
        )

        if end == len(normalized_tokens):
            break

        start = end - overlap
        chunk_index += 1

    return chunks
