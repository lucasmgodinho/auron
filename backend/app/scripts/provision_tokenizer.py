"""Explicitly provision or check tiktoken's validated production assets.

Run from backend/: python -m app.scripts.provision_tokenizer [--check]
--check blocks network access and fails if the existing cache is missing/invalid.
"""

import argparse
from unittest.mock import patch

from app.modules.competitive_intelligence.document_processing import (
    EMBEDDING_MODEL,
    get_tokenizer,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate cached assets offline")
    args = parser.parse_args()
    if args.check:
        unavailable = RuntimeError(
            "Tokenizer assets missing or invalid. Run python -m "
            "app.scripts.provision_tokenizer explicitly with network access first."
        )
        with (
            patch("tiktoken.load.read_file", side_effect=unavailable),
            # Tiktoken normally deletes corrupt assets before re-fetching them.
            # Checking must preserve those bytes too; only explicit setup repairs.
            patch("tiktoken.load.os.remove", side_effect=unavailable),
        ):
            tokenizer = get_tokenizer()
    else:
        tokenizer = get_tokenizer()
    print(f"Tokenizer ready: {EMBEDDING_MODEL} -> {tokenizer.name}")


if __name__ == "__main__":
    main()
