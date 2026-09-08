"""CLI for CAS+ validation.

Thin entry point so a CAS+ document is checkable without a Claude Code session —
by a script that just wrote one, by a git hook, or by CI:

.. code-block:: bash

    python -m atlas_chat.cli_cas validate --cas projects/p/cas.json
    python -m atlas_chat.cli_cas validate --cas a/cas.json b/cas.json --strict
    python -m atlas_chat.cli_cas validate --discover projects/

Exit codes:
    0 — every document valid
    1 — at least one document invalid
    2 — usage or IO error (no document could be read)

The implementation lives in :mod:`atlas_chat.validation.cas_checker`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from atlas_chat.validation.cas_checker import validate_cas_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli_cas", description="Validate CAS+ documents.")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="Validate one or more CAS+ documents.")
    validate.add_argument(
        "--cas", nargs="*", default=[], metavar="PATH", help="CAS+ document(s) to validate."
    )
    validate.add_argument(
        "--discover",
        metavar="DIR",
        help="Also validate every cas.json found beneath DIR.",
    )
    validate.add_argument(
        "--strict",
        action="store_true",
        help="Treat cross-field warnings as failures.",
    )
    validate.add_argument(
        "--quiet", action="store_true", help="Print nothing; signal through the exit code."
    )
    return parser


def _targets(args: argparse.Namespace) -> list[Path]:
    paths = [Path(p) for p in args.cas]
    if args.discover:
        paths.extend(sorted(Path(args.discover).rglob("cas.json")))
    seen: dict[Path, None] = {}
    for path in paths:
        seen.setdefault(path.resolve(), None)
        continue
    return [Path(p) for p in seen]


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    targets = _targets(args)
    if not targets:
        print("nothing to validate: pass --cas and/or --discover", file=sys.stderr)
        return 2

    failed = False
    for target in targets:
        passed, messages = validate_cas_file(target, strict=args.strict)
        if not passed:
            failed = True
        if args.quiet:
            continue
        label = "OK" if passed else "FAILED"
        print(f"{label}: {target}")
        for message in messages:
            print(f"  - {message}")
    return 1 if failed else 0


__all__ = ["build_parser", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
