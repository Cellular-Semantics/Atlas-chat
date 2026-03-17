"""Registry pointing to JSON Schema documents housed in this package."""

from __future__ import annotations

from importlib import resources
from json import loads
from typing import Any, Dict


def load_schema(name: str) -> Dict[str, Any]:
    """Load a JSON schema file bundled in the `schemas` directory."""
    with resources.files(__package__).joinpath(name).open("r", encoding="utf-8") as handle:
        return loads(handle.read())


__all__ = ["load_schema"]
