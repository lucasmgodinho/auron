from datetime import UTC, datetime

import pytest
import tiktoken

from app.modules.competitive_intelligence import document_processing as processing
from app.modules.competitive_intelligence.evidence import SourceDocument


@pytest.mark.parametrize(
    "text",
    [
        "Auron competes with Example Corp. " * 80,
        "Ação, inovação e evidências: 日本語 🚀. " * 60,
        "[Evidence](https://example.com)\n\n\nMore context. " * 55,
        "",
    ],
)
@pytest.mark.parametrize("chunk_size,overlap", [(512, 64), (13, 3)])
def test_chunking_matches_original_production_tokenization(text, chunk_size, overlap):
    document = SourceDocument(
        source_id="parity",
        research_query="Competitors?",
        title="Parity",
        url="https://example.com/parity",
        domain="example.com",
        content=text,
        raw_content=text,
        content_source="search_raw",
        retrieved_at=datetime.now(UTC),
    )
    # Real tiktoken assets are required: no skip, fake or approximate encoder.
    original = tiktoken.encoding_for_model("text-embedding-3-small")
    assert original.name == processing.TOKENIZER_NAME == "cl100k_base"
    assert processing.get_tokenizer().name == original.name
    tokens = original.encode(processing.normalize_document_text(text))
    expected = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        expected.append((original.decode(tokens[start:end]), end - start))
        if end == len(tokens):
            break
        start = end - overlap
    actual = processing.chunk_document(document, chunk_size=chunk_size, overlap=overlap)
    assert [(chunk.text, chunk.token_count) for chunk in actual] == expected
    assert [chunk.chunk_id for chunk in actual] == [
        f"parity_chunk_{index}" for index in range(len(expected))
    ]
    assert all(chunk.source_id == "parity" for chunk in actual)


def test_special_token_rejection_is_preserved():
    document = SourceDocument(
        source_id="special",
        research_query="Competitors?",
        title="Special token",
        url="https://example.com/special",
        domain="example.com",
        content="<|endoftext|>",
        content_source="search_content",
        retrieved_at=datetime.now(UTC),
    )
    with pytest.raises(ValueError, match="disallowed special token"):
        processing.chunk_document(document)
