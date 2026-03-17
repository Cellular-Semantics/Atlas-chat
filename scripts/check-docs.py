#!/usr/bin/env python
"""Helper to build documentation with warnings as errors."""

from __future__ import annotations

import subprocess
from pathlib import Path


def main() -> None:
    docs_dir = Path(__file__).resolve().parents[1] / "docs"
    build_dir = docs_dir / "_build"
    build_dir.mkdir(parents=True, exist_ok=True)

    cmd = ["sphinx-build", str(docs_dir), str(build_dir), "-W"]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
