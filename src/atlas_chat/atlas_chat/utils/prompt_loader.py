"""Load co-located YAML prompt files for agents and services."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


_AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


def load_prompt(name: str, directory: Path | None = None) -> dict[str, Any]:
    """Load a prompt YAML file by agent/service name.

    Args:
        name: Prompt name without extension (e.g. ``"name_resolver"``).
        directory: Directory to search.  Defaults to the ``agents/`` package
            directory.

    Returns:
        Parsed YAML as a dictionary with keys like ``system_prompt``,
        ``user_prompt``, and ``presets``.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    directory = directory or _AGENTS_DIR
    prompt_path = directory / f"{name}.prompt.yaml"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return yaml.safe_load(prompt_path.read_text())


def render_prompt(template: str, **kwargs: str) -> str:
    """Render a prompt template with the given keyword arguments.

    Uses :meth:`str.format_map` so that missing keys are left as-is rather
    than raising.

    Args:
        template: The prompt template string with ``{variable}`` placeholders.
        **kwargs: Values to substitute.

    Returns:
        The rendered prompt string.
    """

    class _Default(dict):  # type: ignore[type-arg]
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    return template.format_map(_Default(**kwargs))
