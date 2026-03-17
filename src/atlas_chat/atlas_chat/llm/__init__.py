"""Provider-neutral LLM access for atlas_chat.

Uses ``cellsem_llm_client.AgentConnection`` as the abstract interface.
The :func:`create_agent` factory selects the right backend based on
``--provider`` / ``--model`` without leaking provider details into the
rest of the codebase.
"""

from __future__ import annotations

from .factory import create_agent

__all__ = ["create_agent"]
