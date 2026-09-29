
# Retrieval Annotation Guidelines

Version: 2.0.0

Label every candidate chunk exactly once against its case's canonical research question.

- `0` — irrelevant: the chunk does not help answer the question.
- `1` — partially relevant: the chunk provides useful context or supports only part of the answer.
- `2` — highly relevant: the chunk directly identifies or substantively explains a requested
  competitor or alternative in the specified market.

Judge only the exact chunk text. Do not use outside knowledge to repair missing context. Apply the
same standard to all companies and sources. Record uncertainty in `review_flag` or `notes` rather
than guessing. Machine suggestions may be stored separately in `suggested_relevance`, but the
final `relevance` value must be assigned or confirmed by a human reviewer. After review, set
`annotation_method` to a value containing `human` and provide `annotated_at` in UTC.
