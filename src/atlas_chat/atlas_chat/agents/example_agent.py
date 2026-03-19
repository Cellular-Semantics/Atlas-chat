"""Example agent demonstrating infrastructure patterns.

EXAMPLE: Replace this entire file with your domain-specific agent logic.
INFRASTRUCTURE: The patterns shown here (schema-first, prompt-first,
co-located prompts) are standard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class ExampleInput(BaseModel):
    """Example input model.

    EXAMPLE: This would be generated from schemas/example_input.schema.json.
    INFRASTRUCTURE: Always generate Pydantic models from JSON schemas programmatically.
    """

    query: str
    max_results: int = 10


class ExampleOutput(BaseModel):
    """Example output model.

    EXAMPLE: Replace with your domain output structure.
    """

    status: str
    result: str
    metadata: dict[str, Any]


def load_prompt(prompt_file: str) -> dict[str, Any]:
    """Load co-located prompt file.

    INFRASTRUCTURE: Always load prompts from YAML files, never hardcode them.
    Co-locate prompts with the agents/services that use them.

    Args:
        prompt_file: Name of .prompt.yaml file in same directory (e.g., "example_agent.prompt.yaml")

    Returns:
        Dictionary containing prompt configuration (system_prompt, user_prompt, presets)

    Example:
        .. code-block:: python

            prompt_config = load_prompt("example_agent.prompt.yaml")
            system_prompt = prompt_config["system_prompt"]
            user_prompt = prompt_config["user_prompt"].format(query="test")
    """
    prompt_path = Path(__file__).parent / prompt_file
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return yaml.safe_load(prompt_path.read_text())


def run_example_agent(input_data: ExampleInput) -> ExampleOutput:
    """Execute example agent workflow.

    EXAMPLE: Replace with your domain-specific agent logic.
    INFRASTRUCTURE: Keep the pattern:
        1. Load co-located prompt
        2. Validate input with Pydantic (from JSON schema)
        3. Execute workflow
        4. Return validated output

    Args:
        input_data: Validated input model (generated from JSON schema)

    Returns:
        Validated output model

    Example:
        .. code-block:: python

            from atlas-chat.agents.example_agent import run_example_agent, ExampleInput

            result = run_example_agent(
                ExampleInput(query="What is agentic AI?", max_results=5)
            )
            print(result.status)  # "completed"
    """
    # INFRASTRUCTURE: Load co-located prompt
    prompt_config = load_prompt("example_agent.prompt.yaml")

    # EXAMPLE: Your actual workflow logic would go here
    # - Use prompt_config to build LLM request
    # - Call external services (LLM, APIs, etc.)
    # - Process results
    # - Return validated output

    # For now, just demonstrate the pattern
    _system_prompt = prompt_config["system_prompt"]  # noqa: F841
    _user_prompt = prompt_config["user_prompt"].format(query=input_data.query)  # noqa: F841

    # Simulated processing (replace with real logic)
    preset = prompt_config.get("presets", {}).get("openai-gpt4", {})
    result = ExampleOutput(
        status="completed",
        result=f"Processed query: {input_data.query}",
        metadata={
            "max_results": input_data.max_results,
            "prompt_used": "example_agent.prompt.yaml",
            "model": preset.get("model", "unknown"),
        },
    )

    return result


# EXAMPLE: Additional helper functions for your domain
# INFRASTRUCTURE: Keep functions small, testable, well-documented


def validate_agent_prerequisites() -> bool:
    """Validate agent has required configuration and dependencies.

    INFRASTRUCTURE: Good pattern for startup validation.

    Returns:
        True if prerequisites met, False otherwise
    """
    # Check prompt file exists
    prompt_path = Path(__file__).parent / "example_agent.prompt.yaml"
    return prompt_path.exists()
