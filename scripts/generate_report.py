#!/usr/bin/env python
"""Thin CLI runner for cell-type report generation.

No orchestration logic lives here — the graph handles everything.

Example usage::

    uv run python scripts/generate_report.py \\
        --project fetal_skin_atlas \\
        --cell-type "Iron-recycling macrophage" \\
        --depth 1

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
        "--model",
        default="claude-sonnet-4-20250514",
        help="Anthropic model to use",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    from atlas_chat.services.atlas_paper import load_project_config
    from atlas_chat.graphs.report_graph import run_report_graph

    config = load_project_config(args.project)

    # Validate cell type exists in project annotations
    ann = config.get_annotation(args.cell_type)
    if ann is None:
        print(f"Error: cell type '{args.cell_type}' not found in project annotations.", file=sys.stderr)
        print("Available labels:", file=sys.stderr)
        for a in config.annotations[:10]:
            print(f"  - {a['label']} ({a['scope']})", file=sys.stderr)
        if len(config.annotations) > 10:
            print(f"  ... and {len(config.annotations) - 10} more", file=sys.stderr)
        sys.exit(1)

    result_path = asyncio.run(
        run_report_graph(
            config=config,
            cell_type=args.cell_type,
            depth=args.depth,
            dry_run=args.dry_run,
            model=args.model,
        )
    )

    print(f"\nReport written to: {result_path}")


if __name__ == "__main__":
    main()
