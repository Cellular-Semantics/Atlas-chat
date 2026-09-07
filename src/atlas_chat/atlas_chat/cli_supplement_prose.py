"""CLI for supplementary prose.

Thin entry point so prose extraction is usable without a Claude Code session:

.. code-block:: bash

    python -m atlas_chat.cli_supplement_prose units --store S --doi D
    python -m atlas_chat.cli_supplement_prose record --store S --doi D --verdicts v.json

The implementation lives in :mod:`atlas_chat.services.supplement_prose`.
"""

from __future__ import annotations

from atlas_chat.services.supplement_prose import build_parser, main

__all__ = ["build_parser", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
