"""Provider-neutral agent factory.

Wraps ``cellsem_llm_client`` factories so callers never import a
provider-specific module directly.

All providers go through ``LiteLLMAgent`` under the hood — the
``provider`` argument just selects the default model and ensures the
model string has the right LiteLLM prefix.
"""

from __future__ import annotations

import logging
import os

from cellsem_llm_client import (
    create_litellm_agent,
    load_environment,
)
from cellsem_llm_client.agents.agent_connection import AgentConnection

logger = logging.getLogger(__name__)

# Default models per provider — update as better models become available.
# Model strings must be valid LiteLLM model identifiers.
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "anthropic/claude-sonnet-4-20250514",
    "openai": "openai/gpt-4.1",
}

# Maps provider name → environment variable holding the API key.
_API_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

PROVIDERS = list(DEFAULT_MODELS)


def create_agent(
    *,
    provider: str = "anthropic",
    model: str | None = None,
    max_tokens: int = 4000,
) -> AgentConnection:
    """Create an LLM agent for the given provider.

    Args:
        provider: One of ``"anthropic"`` or ``"openai"``.
        model: LiteLLM model identifier (e.g. ``"openai/gpt-4.1"``,
            ``"anthropic/claude-sonnet-4-20250514"``).  If ``None``,
            uses the default for the chosen provider.
        max_tokens: Maximum tokens for the response.

    Returns:
        A :class:`~cellsem_llm_client.AgentConnection` instance.

    Raises:
        ValueError: If *provider* is not recognised.
        SystemExit: If credentials are missing (clean error message).
    """
    if provider not in DEFAULT_MODELS:
        raise ValueError(f"Unknown provider: {provider!r}. Choose from: {', '.join(PROVIDERS)}")

    load_environment()
    model = model or DEFAULT_MODELS[provider]

    # Ensure the model string has a provider prefix for LiteLLM
    if "/" not in model:
        model = f"{provider}/{model}"

    # Explicitly resolve the API key — create_litellm_agent's own
    # inference breaks on prefixed model names like "openai/gpt-4.1"
    # because it checks model.startswith("gpt"), not the prefix.
    env_var = _API_KEY_ENV.get(provider, f"{provider.upper()}_API_KEY")
    api_key = os.getenv(env_var)
    if not api_key:
        raise SystemExit(
            f"Error: {env_var} not set.\nSet {env_var} in your .env file or environment."
        )

    logger.info("Creating LLM agent: provider=%s model=%s", provider, model)

    try:
        return create_litellm_agent(model=model, api_key=api_key, max_tokens=max_tokens)
    except ValueError as exc:
        raise SystemExit(f"Error: {exc}\nSet {env_var} in your .env file or environment.") from exc
