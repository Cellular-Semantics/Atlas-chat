"""CLI for subject blocks.

Thin entry point so blocks are inspectable without a Claude Code session:

.. code-block:: bash

    python -m atlas_chat.cli_subject_block --cas cas.json --label "Mast" --min-ratio 0.01

The implementation lives in :mod:`atlas_chat.services.subject_block`.
"""

from __future__ import annotations

from atlas_chat.services.subject_block import build_parser, main

__all__ = ["build_parser", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
