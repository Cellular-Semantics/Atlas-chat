"""Provider-neutral agent factory.

Wraps ``cellsem_llm_client`` factories so callers never import a
provider-specific module directly.
"""

from __future__ import annotations

from cellsem_llm_client import (
    create_anthropic_agent,
    create_litellm_agent,
    create_openai_agent,
    load_environment,
)
from cellsem_llm_client.agents.agent_connection import AgentConnection

# Default models per provider — update as better models become available
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4.1",
    "litellm": "gpt-4.1",
}


def create_agent(
    *,
    provider: str = "anthropic",
    model: str | None = None,
    max_tokens: int = 4000,
) -> AgentConnection:
    """Create an LLM agent for the given provider.

    Args:
        provider: One of ``"anthropic"``, ``"openai"``, or ``"litellm"``.
            ``"litellm"`` auto-detects the backend from the model name,
            so it works for Anthropic, OpenAI, and other providers that
            LiteLLM supports.
        model: Model identifier.  If ``None``, uses the default for the
            chosen provider (see :data:`DEFAULT_MODELS`).
        max_tokens: Maximum tokens for the response.

    Returns:
        A :class:`~cellsem_llm_client.AgentConnection` instance.

    Raises:
        ValueError: If *provider* is not recognised or credentials are
            missing.
    """
    load_environment()
    model = model or DEFAULT_MODELS.get(provider, DEFAULT_MODELS["litellm"])

    if provider == "anthropic":
        return create_anthropic_agent(model=model, max_tokens=max_tokens)
    if provider == "openai":
        return create_openai_agent(model=model, max_tokens=max_tokens)
    if provider == "litellm":
        return create_litellm_agent(model=model, max_tokens=max_tokens)

    raise ValueError(
        f"Unknown provider: {provider!r}. "
        f"Choose from: anthropic, openai, litellm"
    )
