"""CLI entry point for subatlas contribution scoring.

Thin re-export — the parser and the work both live in
:mod:`atlas_chat.services.subatlas_scoring`, so the scoring is callable from
anything and does not need a Claude Code session to run.

.. code-block:: bash

    python -m atlas_chat.cli_subatlas_scores \\
      --cas projects/my_atlas/cas.json \\
      --scores-out projects/my_atlas/subatlas_scores.json \\
      --plan-out   projects/my_atlas/subatlas_read_plan.json \\
      --sensitivity
"""

from __future__ import annotations

from atlas_chat.services.subatlas_scoring import build_parser, main

__all__ = ["build_parser", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
