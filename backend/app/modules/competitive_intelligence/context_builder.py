from .evidence import RetrievedEvidence, SourceDocument


def build_research_context(
    retrieved: list[RetrievedEvidence],
    sources: list[SourceDocument],
) -> str:
    source_by_id = {source.source_id: source for source in sources}

    context_blocks: list[str] = []

    for index, evidence in enumerate(
        retrieved,
        start=1,
    ):
        
        source = source_by_id.get(
            evidence.source_id
        )

        if source is None:
            raise ValueError(
            "SourceDocument not found for "
            f"source_id={evidence.source_id}"
        )

        evidence_id = f"E{index}"

        published_date = source.published_date.isoformat() if source.published_date else "Unknown"

        block = f"""
        <EVIDENCE id="{evidence_id}">
        Title: {source.title}
        URL: {source.url}
        Published date: {published_date}

        Content:
        {evidence.text}
        </EVIDENCE>
        """.strip()

        context_blocks.append(block)

    return "\n\n".join(context_blocks)
