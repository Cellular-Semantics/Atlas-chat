"""Integration between declarative workflow graphs and Pydantic AI agents."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai import Agent, RunContext

from .definitions import GraphNode, WorkflowGraph

DEFAULT_LLM_MODEL = "gpt-4.1"


@dataclass
class GraphDependencies:
    """Dependencies available to the graph agent during execution."""

    graph: WorkflowGraph


def build_graph_agent(model: str = DEFAULT_LLM_MODEL) -> Agent[GraphDependencies, GraphNode]:
    """Construct a Pydantic AI agent to navigate workflow graphs."""

    instructions = (
        "You are an orchestration agent operating over a validated workflow graph. "
        "Use the registered tools to inspect nodes and decide the next step. "
        "Always return the node configuration needed by downstream services."
    )

    agent = Agent(
        model,
        deps_type=GraphDependencies,
        output_type=GraphNode,
        instructions=instructions,
    )

    @agent.tool
    def fetch_node(ctx: RunContext[GraphDependencies], node_id: str) -> GraphNode:
        """Retrieve a node definition from the workflow graph."""
        return ctx.deps.graph.route(node_id)

    return agent
