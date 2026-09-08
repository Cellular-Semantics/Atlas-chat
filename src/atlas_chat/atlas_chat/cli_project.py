"""CLI for resolving a project's paths.

Thin entry point so a caller needs only the project's name:

.. code-block:: bash

    python -m atlas_chat.cli_project --project hca_reproductive

The implementation lives in :mod:`atlas_chat.services.project_paths`.
"""

from __future__ import annotations

from atlas_chat.services.project_paths import build_parser, main

__all__ = ["build_parser", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
