"""Core package for atlas-chat."""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()


def bootstrap() -> None:
    """Load environment configuration required for agent workflows."""
