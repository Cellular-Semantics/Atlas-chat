from __future__ import annotations

import os

import pytest

REQUIRED_ENV_VARS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")


@pytest.mark.integration
def test_required_api_keys_present() -> None:
    """Ensure developers configure real API keys before running integrations."""
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    assert not missing, f"Missing integration environment variables: {missing}"
