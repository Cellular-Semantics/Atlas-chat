#!/usr/bin/env python
"""Thin CLI runner for cell-type report generation.

No orchestration logic lives here — the graph handles everything.

Example usage::

    # With Anthropic (default)
    uv run python scripts/generate_report.py \\
        --project fetal_skin_atlas \\
        --cell-type "Iron-recycling macrophage"

    # With OpenAI
    uv run python scripts/generate_report.py \\
        --project fetal_skin_atlas \\
        --cell-type "Iron-recycling macrophage" \\
        --provider openai

    # Specific model
    uv run python scripts/generate_report.py \\
        --project fetal_skin_atlas \\
        --cell-type "Iron-recycling macrophage" \\
        --provider openai --model gpt-4.1

    # Dry run (no LLM calls)
    uv run python scripts/generate_report.py \\
        --project fetal_skin_atlas \\
        --cell-type "Iron-recycling macrophage" \\
        --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import traceback


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a cell-type report from an atlas project."
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Project directory name under projects/",
    )
    parser.add_argument(
        "--cell-type",
        required=True,
        help="Cell type annotation label (e.g. 'Iron-recycling macrophage')",
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
    # Third-party libs (litellm, httpx, httpcore, etc.) stay at WARNING.
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logging.getLogger("atlas_chat").setLevel(
        logging.DEBUG if args.verbose else logging.INFO
    )

    try:
        _run(args)
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


def _run(args: argparse.Namespace) -> None:
    from atlas_chat.services.atlas_paper import load_project_config
    from atlas_chat.llm.factory import DEFAULT_MODELS
    from atlas_chat.utils.prompt_loader import load_prompt

    config = load_project_config(args.project)

    # Validate cell type exists in project annotations
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

    if args.dry_run:
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


def _show_plan(
    args: argparse.Namespace,
    config: "AtlasConfig",
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
        ("1", "FetchSupplements",
         "Resolve DOI → PMCID via Europe PMC, fetch full text + supplements"),
        ("2", "ResolveName",
         "LLM call: identify author terminology for this cell type"),
        ("3a", "ScanSupplements  [parallel]",
         "LLM call: scan supplementary material for markers & findings"),
        ("3b", "CitationTraverse [parallel]",
         f"ASTA snippet search (depth={args.depth}), build paper catalogue"),
        ("4", "SynthesizeReport",
         "LLM call: generate markdown report from all evidence"),
        ("5", "ValidateReport",
         "Check quotes against evidence, check CorpusId refs (max 2 retries)"),
        ("6", "SaveReport",
         f"Write to {reports_dir}/{args.cell_type}.md"),
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
