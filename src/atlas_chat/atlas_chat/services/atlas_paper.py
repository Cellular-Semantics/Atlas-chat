"""Services for fetching atlas paper data: full text, supplements, ID resolution.

These are thin wrappers intended for use by the PydanticAI graph nodes.
In the agentic (Claude Code) workflow, the agent calls MCP tools directly —
these functions are the programmatic equivalent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AtlasConfig:
    """Configuration loaded from a project's ``cell_type_annotations.json``."""

    doi: str
    title: str
    annotations: list[dict[str, str]]
    project_dir: Path
    pmcid: str | None = None
    corpus_id: str | None = None

    @classmethod
    def from_project(cls, project_dir: Path) -> AtlasConfig:
        """Load config from a project directory.

        Args:
            project_dir: Path to the project directory containing
                ``cell_type_annotations.json``.

        Returns:
            Populated :class:`AtlasConfig`.
        """
        config_path = project_dir / "cell_type_annotations.json"
        data = json.loads(config_path.read_text())
        source = data["source"]
        return cls(
            doi=source["doi"],
            title=source["title"],
            annotations=data["annotations"],
            project_dir=project_dir,
            pmcid=source.get("pmcid"),
            corpus_id=source.get("corpus_id"),
        )

    def get_annotation(self, label: str) -> dict[str, str] | None:
        """Find an annotation entry by label."""
        for ann in self.annotations:
            if ann["label"] == label:
                return ann
        return None

    def traversal_dir(self, cell_type: str) -> Path:
        """Return the traversal output directory for a cell type, creating it."""
        d = self.project_dir / "traversal_output" / cell_type
        d.mkdir(parents=True, exist_ok=True)
        return d

    def reports_dir(self) -> Path:
        """Return the reports directory, creating it."""
        d = self.project_dir / "reports"
        d.mkdir(parents=True, exist_ok=True)
        return d


@dataclass
class PaperIdentifiers:
    """All identifiers resolved for a paper."""

    doi: str
    pmid: str | None = None
    pmcid: str | None = None
    corpus_id: str | None = None


@dataclass
class AtlasPaperData:
    """Container for data fetched about the atlas paper."""

    full_text: str = ""
    supplementary_files: list[dict[str, Any]] = field(default_factory=list)
    identifiers: PaperIdentifiers | None = None


def load_project_config(project_name: str) -> AtlasConfig:
    """Load project configuration by name.

    Searches for the project directory under ``projects/``.

    Args:
        project_name: The project directory name.

    Returns:
        Populated :class:`AtlasConfig`.

    Raises:
        FileNotFoundError: If the project directory or config file doesn't exist.
    """
    # Walk up from this file to find the repo root (contains pyproject.toml)
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / "projects").is_dir():
            break
        current = current.parent
    else:
        raise FileNotFoundError("Could not find projects/ directory")

    project_dir = current / "projects" / project_name
    if not project_dir.exists():
        raise FileNotFoundError(f"Project directory not found: {project_dir}")

    return AtlasConfig.from_project(project_dir)
