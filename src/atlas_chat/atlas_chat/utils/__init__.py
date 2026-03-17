"""Repo-specific utilities that do not belong in agents/services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


def chunk_items(items: Iterable[str], size: int = 10) -> List[List[str]]:
    """Simple batching helper for splitting sequences in tooling scripts."""
    batch: List[str] = []
    result: List[List[str]] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            result.append(batch)
            batch = []
    if batch:
        result.append(batch)
    return result


@dataclass
class ToolingContext:
    """Context object that CLI scripts can extend with repo-specific settings."""

    workspace: str
    dry_run: bool = False

