#!/usr/bin/env python
"""End-to-end smoke checks for atlas_chat.

Verifies that all three modes (programmatic, agentic, chat) are structurally
intact without making any API calls.  Run this before and after any structural
changes (especially Phase 1 cleanup).

Usage:
    uv run python scripts/e2e_smoke.py

Exit code 0 = all checks passed.
Exit code 1 = one or more checks failed.
"""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = REPO_ROOT / "projects"

# Representative reports for golden-data regression (must have traversal data)
GOLDEN_CELL_TYPES = ["Macro_1", "Treg", "NK"]
GOLDEN_PROJECT = "fetal_skin_atlas"

# All prompt YAML names that must load via prompt_loader
PROMPT_NAMES = [
    "name_resolver",
    "supplementary_scanner",
    "snippet_summarizer",
    "report_synthesizer",
    "orchestrator",
]

# Markdown files with @ path references to verify
MD_FILES_WITH_REFS = [
    REPO_ROOT / "AGENT.md",
]

# Subagent definition files that may contain path references
SUBAGENT_FILES = list((REPO_ROOT / ".claude" / "agents").glob("*.md"))


class Results:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.skipped: list[str] = []

    def ok(self, name: str) -> None:
        self.passed.append(name)
        print(f"  PASS  {name}")

    def fail(self, name: str, reason: str) -> None:
        self.failed.append(name)
        print(f"  FAIL  {name}: {reason}")

    def skip(self, name: str, reason: str) -> None:
        self.skipped.append(name)
        print(f"  SKIP  {name}: {reason}")

    def summary(self) -> int:
        total = len(self.passed) + len(self.failed) + len(self.skipped)
        print(f"\n{'='*60}")
        print(f"  {len(self.passed)} passed, {len(self.failed)} failed, "
              f"{len(self.skipped)} skipped  (total {total})")
        if self.failed:
            print("\nFailed checks:")
            for name in self.failed:
                print(f"  - {name}")
        print()
        return 1 if self.failed else 0


def check_imports(r: Results) -> None:
    """Verify core imports resolve."""
    print("\n--- Core imports ---")

    modules = [
        ("atlas_chat.validation.report_checker", "validate_report"),
        ("atlas_chat.services.atlas_paper", "load_project_config"),
        ("atlas_chat.utils.prompt_loader", "load_prompt"),
        ("atlas_chat.cli", "main"),
    ]
    for mod_name, attr in modules:
        try:
            mod = importlib.import_module(mod_name)
            if not hasattr(mod, attr):
                r.fail(f"import {mod_name}.{attr}", f"attribute {attr!r} not found")
                continue
            r.ok(f"import {mod_name}.{attr}")
        except Exception as exc:
            r.fail(f"import {mod_name}.{attr}", str(exc))


def check_prompt_loading(r: Results) -> None:
    """Verify all prompt YAMLs load via prompt_loader."""
    print("\n--- Prompt YAML loading ---")

    try:
        from atlas_chat.utils.prompt_loader import load_prompt
    except ImportError as exc:
        r.fail("prompt_loader import", str(exc))
        return

    for name in PROMPT_NAMES:
        try:
            data = load_prompt(name)
            if not isinstance(data, dict):
                r.fail(f"load_prompt({name!r})", "did not return a dict")
                continue
            r.ok(f"load_prompt({name!r})")
        except Exception as exc:
            r.fail(f"load_prompt({name!r})", str(exc))


def check_project_config(r: Results) -> None:
    """Verify project config loading."""
    print("\n--- Project config ---")

    project_dir = PROJECTS_DIR / GOLDEN_PROJECT
    if not project_dir.exists():
        r.skip("load_project_config", f"project dir {project_dir} not found")
        return

    config_path = project_dir / "cell_type_annotations.json"
    if not config_path.exists():
        r.skip("load_project_config", f"config file {config_path} not found")
        return

    try:
        from atlas_chat.services.atlas_paper import load_project_config

        config = load_project_config(GOLDEN_PROJECT)
        if not config.doi:
            r.fail("load_project_config", "DOI is empty")
            return
        r.ok(f"load_project_config({GOLDEN_PROJECT!r}) → DOI={config.doi}")
    except Exception as exc:
        r.fail("load_project_config", str(exc))


def check_golden_reports(r: Results) -> None:
    """Run validate_report on golden cell types."""
    print("\n--- Golden-data regression ---")

    project_dir = PROJECTS_DIR / GOLDEN_PROJECT
    if not project_dir.exists():
        r.skip("golden reports", f"project dir {project_dir} not found")
        return

    try:
        from atlas_chat.validation.report_checker import validate_report
    except ImportError as exc:
        r.fail("golden reports import", str(exc))
        return

    for ct in GOLDEN_CELL_TYPES:
        report_path = project_dir / "reports" / f"{ct}.md"
        traversal_dir = project_dir / "traversal_output" / ct

        if not report_path.exists():
            r.skip(f"validate({ct})", "report file missing")
            continue
        if not traversal_dir.exists():
            r.skip(f"validate({ct})", "traversal dir missing")
            continue

        try:
            passed, errors = validate_report(report_path, traversal_dir)
            if passed:
                r.ok(f"validate({ct})")
            else:
                r.fail(f"validate({ct})", "; ".join(errors[:3]))
        except Exception as exc:
            r.fail(f"validate({ct})", str(exc))


def check_at_path_references(r: Results) -> None:
    """Verify @ path references in AGENT.md resolve to real files."""
    print("\n--- @ path references ---")

    at_pattern = re.compile(r"^@(.+)$", re.MULTILINE)

    for md_file in MD_FILES_WITH_REFS:
        if not md_file.exists():
            r.skip(f"@refs in {md_file.name}", "file not found")
            continue

        text = md_file.read_text()
        refs = at_pattern.findall(text)
        if not refs:
            r.ok(f"@refs in {md_file.name} (none found)")
            continue

        for ref in refs:
            ref = ref.strip()
            target = REPO_ROOT / ref
            if target.exists():
                r.ok(f"@{ref}")
            else:
                r.fail(f"@{ref}", f"file not found (referenced in {md_file.name})")


def check_hook_import(r: Results) -> None:
    """Verify the Claude Code hook can import validation."""
    print("\n--- Hook import ---")

    hook_path = REPO_ROOT / ".claude" / "hooks" / "check_report_refs.py"
    if not hook_path.exists():
        r.skip("hook import", "check_report_refs.py not found")
        return

    try:
        from atlas_chat.validation.report_checker import validate_report  # noqa: F811

        r.ok("hook imports atlas_chat.validation.report_checker")
    except ImportError as exc:
        r.fail("hook imports atlas_chat.validation.report_checker", str(exc))


def check_cli_dry_run(r: Results) -> None:
    """Verify atlas-report --dry-run works (if project data available)."""
    print("\n--- CLI dry-run ---")

    project_dir = PROJECTS_DIR / GOLDEN_PROJECT
    config_path = project_dir / "cell_type_annotations.json"
    if not config_path.exists():
        r.skip("CLI --dry-run", "project config not found")
        return

    try:
        result = subprocess.run(
            [
                "uv", "run", "atlas-report",
                "--project", GOLDEN_PROJECT,
                "--cell-type", "Macro_1",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=REPO_ROOT,
        )
        if result.returncode == 0:
            r.ok("atlas-report --dry-run")
        else:
            stderr = result.stderr.strip()[:200]
            r.fail("atlas-report --dry-run", f"exit {result.returncode}: {stderr}")
    except FileNotFoundError:
        r.skip("CLI --dry-run", "uv not found")
    except subprocess.TimeoutExpired:
        r.fail("CLI --dry-run", "timed out after 30s")


def check_chat_references(r: Results) -> None:
    """Verify CHAT.md exists and load-project-context skill exists."""
    print("\n--- Chat mode ---")

    chat_md = REPO_ROOT / "CHAT.md"
    if chat_md.exists():
        r.ok("CHAT.md exists")
    else:
        r.fail("CHAT.md exists", "file not found")

    skill_path = REPO_ROOT / ".claude" / "skills" / "load-project-context.md"
    if skill_path.exists():
        r.ok("load-project-context skill exists")
    else:
        r.fail("load-project-context skill exists", "file not found")


def main() -> int:
    print("atlas_chat e2e smoke checks")
    print(f"Repo root: {REPO_ROOT}")

    r = Results()

    check_imports(r)
    check_prompt_loading(r)
    check_project_config(r)
    check_golden_reports(r)
    check_at_path_references(r)
    check_hook_import(r)
    check_cli_dry_run(r)
    check_chat_references(r)

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
