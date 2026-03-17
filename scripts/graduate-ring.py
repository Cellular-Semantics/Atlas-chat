"""Graduate this project from Ring 0 to Ring 1 quality enforcement.

Usage:
    python scripts/graduate-ring.py --to 1

What it does (--to 1):
    - .githooks/pre-commit  : raises coverage floor 60 → 80, adds mypy
    - .github/workflows/test.yml : raises coverage floor 60 → 80, adds mypy step
    - pyproject.toml        : raises fail_under 60 → 80

Run this when Ring 0 has shipped and been validated with users, before starting Ring 1.
The script is idempotent — safe to run more than once.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _patch(path: Path, old: str, new: str, description: str) -> bool:
    """Replace old with new in path. Returns True if a change was made."""
    text = path.read_text()
    if old not in text:
        if new in text:
            print(f"  [already done] {description}")
        else:
            print(f"  [WARNING] Could not find pattern to patch in {path.name}: {old!r}")
        return False
    path.write_text(text.replace(old, new, 1))
    print(f"  [patched] {description}")
    return True


def graduate_to_ring1() -> None:
    print("\nGraduating to Ring 1 quality enforcement...\n")
    changed: list[str] = []

    # --- .githooks/pre-commit ---
    hook = REPO_ROOT / ".githooks" / "pre-commit"
    if not hook.exists():
        print(f"  [WARNING] {hook} not found — skipping")
    else:
        if _patch(
            hook,
            "# Ring 0 defaults — run scripts/graduate-ring.py --to 1 when Ring 0 ships",
            "# Ring 1 enforcement — mypy + 80% coverage",
            "pre-commit: update header comment",
        ):
            changed.append(str(hook))
        if _patch(
            hook,
            "uv run pytest -m unit --cov --cov-fail-under=60",
            "uv run pytest -m unit --cov --cov-fail-under=80",
            "pre-commit: raise coverage floor 60 → 80",
        ):
            changed.append(str(hook))
        # Insert mypy before the pytest line if not already there
        hook_text = hook.read_text()
        if "uv run mypy" not in hook_text:
            hook.write_text(
                hook_text.replace(
                    'echo "[githook] Running unit tests with coverage..."',
                    'echo "[githook] Running mypy type checking..."\n'
                    "uv run mypy src/\n\n"
                    'echo "[githook] Running unit tests with coverage..."',
                )
            )
            print("  [patched] pre-commit: add mypy type checking")
            changed.append(str(hook))

    # --- .github/workflows/test.yml ---
    ci = REPO_ROOT / ".github" / "workflows" / "test.yml"
    if not ci.exists():
        print(f"  [WARNING] {ci} not found — skipping")
    else:
        if _patch(
            ci,
            "# Ring 0 defaults — run scripts/graduate-ring.py --to 1 when Ring 0 ships",
            "# Ring 1 enforcement — mypy + 80% coverage",
            "test.yml: update header comment",
        ):
            changed.append(str(ci))
        if _patch(
            ci,
            "uv run pytest -m unit --cov --cov-fail-under=60 --cov-report=xml",
            "uv run pytest -m unit --cov --cov-fail-under=80 --cov-report=xml",
            "test.yml: raise coverage floor 60 → 80",
        ):
            changed.append(str(ci))
        # Insert mypy step before unit tests if not already there
        ci_text = ci.read_text()
        if "uv run mypy" not in ci_text:
            ci.write_text(
                ci_text.replace(
                    "      - name: Unit tests with coverage",
                    "      - name: Type check\n"
                    "        run: uv run mypy src/\n\n"
                    "      - name: Unit tests with coverage",
                )
            )
            print("  [patched] test.yml: add mypy type check step")
            changed.append(str(ci))

    # --- pyproject.toml ---
    pyproject = REPO_ROOT / "pyproject.toml"
    if not pyproject.exists():
        print(f"  [WARNING] {pyproject} not found — skipping")
    else:
        if _patch(
            pyproject,
            "# Ring 0 default — run scripts/graduate-ring.py --to 1 to raise this to 80\nfail_under = 60",
            "# Ring 1 enforcement\nfail_under = 80",
            "pyproject.toml: raise coverage fail_under 60 → 80",
        ):
            changed.append(str(pyproject))

    # --- Summary ---
    print()
    if changed:
        unique = sorted(set(changed))
        print(f"Done. {len(unique)} file(s) updated:")
        for f in unique:
            print(f"  {Path(f).relative_to(REPO_ROOT)}")
        print()
        print("Next steps:")
        print("  1. Review the changes: git diff")
        print("  2. Run the full quality suite: uv run pytest -m unit --cov && uv run mypy src/")
        print("  3. Fix any type errors or coverage gaps before committing")
        print("  4. Update CLAUDE.md: mark Ring 0 complete, define Ring 1 scope")
    else:
        print("No changes made — project may already be at Ring 1.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Graduate this project to the next ring of quality enforcement."
    )
    parser.add_argument(
        "--to",
        type=int,
        required=True,
        metavar="RING",
        help="Target ring number (currently only 1 is supported)",
    )
    args = parser.parse_args()

    if args.to == 1:
        graduate_to_ring1()
    else:
        print(f"Error: --to {args.to} is not yet supported. Only --to 1 is implemented.")
        sys.exit(1)


if __name__ == "__main__":
    main()
