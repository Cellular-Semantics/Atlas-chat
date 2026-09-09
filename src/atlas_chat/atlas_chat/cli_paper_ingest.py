"""CLI for assembling one paper's readable content.

Thin entry point so the ingest is usable without a Claude Code session:

.. code-block:: bash

    python -m atlas_chat.cli_paper_ingest --text paper.jats.xml --out ingest.json \
        --doi 10.0000/example --store <supplement store> --limit-tokens 60000

The implementation lives in :mod:`atlas_chat.services.paper_ingest`.
"""

from __future__ import annotations

from atlas_chat.services.paper_ingest import build_parser, main

__all__ = ["build_parser", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
