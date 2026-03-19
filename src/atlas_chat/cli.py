"""CLI entry point for cell-type report generation.

Supports single cell-type runs, batch mode (all annotations), and a
``--no-stomp`` flag that skips cell types whose report already exists.

Console script::

    atlas-report --project fetal_skin_atlas --cell-type "DC1"
    atlas-report --project fetal_skin_atlas --batch
    atlas-report --project fetal_skin_atlas --batch --no-stomp
    atlas-report --project fetal_skin_atlas --batch --no-stomp --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atlas_chat.services.atlas_paper import AtlasConfig


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a cell-type report from an atlas project.",
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Project directory name under projects/",
    )

    # --cell-type and --batch are mutually exclusive; one is required.
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--cell-type",
        help="Cell type annotation label (e.g. 'Iron-recycling macrophage')",
    )
    group.add_argument(
        "--batch",
        action="store_true",
        help="Generate reports for all annotations in the project",
    )

    parser.add_argument(
        "--no-stomp",
        action="store_true",
        help="Skip cell types whose report file already exists",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=1,
        help="Citation traversal depth (default: 1, max: 3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show plan without executing LLM calls",
    )
    parser.add_argument(
        "--provider",
        default="anthropic",
        choices=["anthropic", "openai"],
        help="LLM provider (default: anthropic)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "LiteLLM model identifier. If omitted, uses provider default. "
            "Examples: claude-sonnet-4-20250514, gpt-4.1"
        ),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging (includes full stack traces)",
    )
    args = parser.parse_args()

    # Configure logging: only atlas_chat loggers get DEBUG in verbose mode.
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logging.getLogger("atlas_chat").setLevel(logging.DEBUG if args.verbose else logging.INFO)

    try:
        if args.batch:
            _run_batch(args)
        else:
            _run_single(args)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        if args.verbose:
            traceback.print_exc()
        else:
            print(f"Error: {exc}", file=sys.stderr)
            print("Run with --verbose for full stack trace.", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _report_path(config: AtlasConfig, cell_type: str) -> Path:
    """Return the expected report file path for a cell type."""
    return config.project_dir / "reports" / f"{cell_type}.md"


def _report_exists(config: AtlasConfig, cell_type: str) -> bool:
    return _report_path(config, cell_type).is_file()


# ---------------------------------------------------------------------------
# Single cell-type run
# ---------------------------------------------------------------------------


def _run_single(args: argparse.Namespace) -> None:
    from atlas_chat.services.atlas_paper import load_project_config

    config = load_project_config(args.project)

    ann = config.get_annotation(args.cell_type)
    if ann is None:
        print(
            f"Error: cell type '{args.cell_type}' not found in project annotations.",
            file=sys.stderr,
        )
        print("Available labels:", file=sys.stderr)
        for a in config.annotations[:10]:
            print(f"  - {a['label']} ({a['scope']})", file=sys.stderr)
        if len(config.annotations) > 10:
            print(f"  ... and {len(config.annotations) - 10} more", file=sys.stderr)
        sys.exit(1)

    if args.no_stomp and _report_exists(config, args.cell_type):
        print(f"Skipping (report exists): {args.cell_type}")
        return

    if args.dry_run:
        from atlas_chat.llm.factory import DEFAULT_MODELS

        _show_plan(args, config, ann, DEFAULT_MODELS)
        return

    from atlas_chat.graphs.report_graph import run_report_graph

    result_path = asyncio.run(
        run_report_graph(
            config=config,
            cell_type=args.cell_type,
            depth=args.depth,
            provider=args.provider,
            model=args.model,
        )
    )
    print(f"\nReport written to: {result_path}")


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------


def _run_batch(args: argparse.Namespace) -> None:
    from atlas_chat.services.atlas_paper import load_project_config

    config = load_project_config(args.project)
    annotations = config.annotations
    total = len(annotations)

    if total == 0:
        print("No annotations found in project.", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        _show_batch_plan(args, config, annotations)
        return

    from atlas_chat.graphs.report_graph import run_report_graph

    failures: list[tuple[str, str]] = []
    skipped = 0
    generated = 0

    for idx, ann in enumerate(annotations, 1):
        label = ann["label"]
        prefix = f"[{idx}/{total}]"

        if args.no_stomp and _report_exists(config, label):
            print(f"{prefix} Skipping (report exists): {label}")
            skipped += 1
            continue

        print(f"{prefix} Generating: {label} ...")
        try:
            result_path = asyncio.run(
                run_report_graph(
                    config=config,
                    cell_type=label,
                    depth=args.depth,
                    provider=args.provider,
                    model=args.model,
                )
            )
            print(f"{prefix} Done: {result_path}")
            generated += 1
        except Exception as exc:
            msg = str(exc)
            failures.append((label, msg))
            print(f"{prefix} FAILED: {label} — {msg}", file=sys.stderr)
            if args.verbose:
                traceback.print_exc()

    # Summary
    print("\n" + "=" * 60)
    print("Batch summary")
    print("=" * 60)
    print(f"  Total:     {total}")
    print(f"  Generated: {generated}")
    print(f"  Skipped:   {skipped}")
    print(f"  Failed:    {len(failures)}")
    if failures:
        print("\nFailed cell types:")
        for label, msg in failures:
            print(f"  - {label}: {msg}")
    print()


def _show_batch_plan(
    args: argparse.Namespace,
    config: AtlasConfig,
    annotations: list[dict[str, str]],
) -> None:
    """Dry-run output for batch mode."""
    total = len(annotations)
    print("=" * 60)
    print("DRY RUN — batch plan")
    print("=" * 60)
    print(f"  Project:  {args.project}")
    print(f"  Provider: {args.provider}")
    print(f"  Model:    {args.model or '(default)'}")
    print(f"  Depth:    {args.depth}")
    print(f"  No-stomp: {args.no_stomp}")
    print(f"  Total annotations: {total}")
    print()

    skip_count = 0
    gen_count = 0
    for idx, ann in enumerate(annotations, 1):
        label = ann["label"]
        exists = _report_exists(config, label)
        if args.no_stomp and exists:
            print(f"  [{idx}/{total}] SKIP  {label}")
            skip_count += 1
        else:
            status = " (overwrite)" if exists else ""
            print(f"  [{idx}/{total}] RUN   {label}{status}")
            gen_count += 1

    print()
    print(f"  Would generate: {gen_count}")
    print(f"  Would skip:     {skip_count}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Single dry-run plan (unchanged from original)
# ---------------------------------------------------------------------------


def _show_plan(
    args: argparse.Namespace,
    config: AtlasConfig,
    ann: dict,
    default_models: dict[str, str],
) -> None:
    """Display the execution plan without running anything."""
    from atlas_chat.utils.prompt_loader import load_prompt

    model = args.model or default_models.get(args.provider, "?")
    if "/" not in model:
        model = f"{args.provider}/{model}"

    print("=" * 60)
    print("DRY RUN — execution plan")
    print("=" * 60)

    # 1. Config
    print("\n--- Configuration ---")
    print(f"  Project:    {args.project}")
    print(f"  Cell type:  {args.cell_type}")
    print(f"  Scope:      {ann.get('scope', '?')}")
    print(f"  Granularity:{ann.get('granularity', '?')}")
    print(f"  Atlas DOI:  {config.doi}")
    print(f"  Atlas:      {config.title}")
    print(f"  Provider:   {args.provider}")
    print(f"  Model:      {model}")
    print(f"  Depth:      {args.depth}")

    # 2. Output paths
    traversal_dir = config.project_dir / "traversal_output" / args.cell_type
    reports_dir = config.project_dir / "reports"
    print("\n--- Output paths ---")
    print(f"  Traversal:  {traversal_dir}/")
    print(f"  Report:     {reports_dir}/{args.cell_type}.md")

    # 3. Orchestration steps
    print("\n--- Orchestration sequence ---")
    steps = [
        (
            "1",
            "FetchSupplements",
            "Resolve DOI -> PMCID via Europe PMC, fetch full text + supplements",
        ),
        ("2", "ResolveName", "LLM call: identify author terminology for this cell type"),
        (
            "3a",
            "ScanSupplements  [parallel]",
            "LLM call: scan supplementary material for markers & findings",
        ),
        (
            "3b",
            "CitationTraverse [parallel]",
            f"ASTA snippet search (depth={args.depth}), build paper catalogue",
        ),
        ("4", "SynthesizeReport", "LLM call: generate markdown report from all evidence"),
        (
            "5",
            "ValidateReport",
            "Check quotes against evidence, check CorpusId refs (max 2 retries)",
        ),
        ("6", "SaveReport", f"Write to {reports_dir}/{args.cell_type}.md"),
    ]
    for num, name, desc in steps:
        print(f"  [{num}] {name}")
        print(f"       {desc}")

    # 4. Prompts
    prompt_names = [
        ("name_resolver", "ResolveName"),
        ("supplementary_scanner", "ScanSupplements"),
        ("report_synthesizer", "SynthesizeReport"),
    ]
    print("\n--- Prompts ---")
    for pname, step in prompt_names:
        try:
            prompt = load_prompt(pname)
            print(f"\n  [{step}] {pname}.prompt.yaml")
            for key in ("system_prompt", "user_prompt"):
                text = prompt.get(key, "").strip()
                if text:
                    print(f"\n    {key}:")
                    for line in text.split("\n"):
                        print(f"      {line}")
        except Exception:
            print(f"\n  [{step}] {pname}.prompt.yaml — not found")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
