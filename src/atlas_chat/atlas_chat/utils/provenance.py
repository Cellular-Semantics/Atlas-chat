"""Run provenance capture utilities.

INFRASTRUCTURE: Every workflow run — programmatic or agentic — should call
capture_provenance() before making any LLM calls, including dry-runs.

The returned dict is serialisable to JSON and conforms to
schemas/run_provenance.schema.json.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    """Return sha256 hex digest of a file's content."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_version() -> str:
    """Return git describe output, or 'unknown' if not in a git repo."""
    try:
        return subprocess.check_output(
            ["git", "describe", "--tags", "--always", "--dirty"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _package_version(package_name: str) -> str:
    """Return installed package version, or 'unknown' if not installed."""
    try:
        from importlib.metadata import version

        return version(package_name)
    except Exception:
        return "unknown"


def capture_provenance(
    package_name: str,
    prompts: dict[str, Path],
    schemas_used: dict[str, Path],
    settings: dict[str, Any],
    input_data: Any,
    mode: str = "programmatic",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Capture full provenance for a workflow run.

    Call this before making any LLM calls. Write the result immediately to
    ``outputs/{run_name}/{timestamp}/provenance.json``.

    Args:
        package_name: Importable package name for version lookup.
        prompts: Map of label to Path for each .prompt.yaml used.
        schemas_used: Map of label to Path for each .schema.json used.
        settings: Active model settings (preset, provider, model, temperature).
        input_data: Raw input; sha256 hash is recorded for reproducibility.
        mode: "programmatic" or "agentic".
        dry_run: If True, no LLM calls will be made.

    Returns:
        Provenance dict conforming to run_provenance.schema.json.

    Example:
        .. code-block:: python

            from pathlib import Path
            from atlas-chat.utils.provenance import capture_provenance

            prov = capture_provenance(
                package_name="atlas-chat",
                prompts={"annotator": Path("src/.../annotator.prompt.yaml")},
                schemas_used={"output": Path("src/.../output.schema.json")},
                settings={"preset": "anthropic-claude", "model": "claude-3-sonnet"},
                input_data={"query": "TP53 BRCA1"},
            )
    """
    input_hash = hashlib.sha256(
        json.dumps(input_data, sort_keys=True, default=str).encode()
    ).hexdigest()

    return {
        "run_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "dry_run": dry_run,
        "git_version": _git_version(),
        "package_version": _package_version(package_name),
        "prompts": {
            label: {"path": str(path), "content_hash": _sha256(path)}
            for label, path in prompts.items()
        },
        "schemas_used": {
            label: {"path": str(path), "content_hash": _sha256(path)}
            for label, path in schemas_used.items()
        },
        "settings": settings,
        "input_hash": input_hash,
    }


def format_dry_run_report(
    provenance: dict[str, Any],
    prompt_contents: dict[str, str],
) -> str:
    """Format a human-readable dry-run provenance report.

    Args:
        provenance: Dict returned by capture_provenance() with dry_run=True.
        prompt_contents: Map of prompt label to resolved YAML content string.

    Returns:
        Multi-line string suitable for printing to stdout.

    Example:
        .. code-block:: python

            report = format_dry_run_report(prov, {"annotator": yaml_text})
            print(report)
    """
    lines = [
        "=== DRY RUN ===",
        "",
        "PROVENANCE",
        f"  Git:     {provenance.get('git_version', 'unknown')}",
        f"  Package: {provenance.get('package_version', 'unknown')}",
        f"  Run ID:  {provenance['run_id']}",
        f"  Time:    {provenance['timestamp']}",
        "",
        "PROMPTS",
    ]
    for label, meta in provenance.get("prompts", {}).items():
        lines += [
            f"  {label}  {meta['path']}",
            f"           sha256:{meta['content_hash'][:16]}...",
            "           --- content ---",
        ]
        for content_line in prompt_contents.get(label, "").splitlines():
            lines.append(f"           {content_line}")
        lines.append("")

    lines += ["SCHEMAS"]
    for label, meta in provenance.get("schemas_used", {}).items():
        lines += [
            f"  {label}  {meta['path']}",
            f"           sha256:{meta['content_hash'][:16]}...",
        ]

    lines += ["", "SETTINGS"]
    for key, val in provenance.get("settings", {}).items():
        lines.append(f"  {key}: {val}")

    lines += [
        "",
        "NO CHANGES MADE. Run without --dry-run to execute.",
    ]
    return "\n".join(lines)
