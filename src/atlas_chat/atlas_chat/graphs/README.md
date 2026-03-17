# Graphs - Workflow Orchestration

**Status**: OPTIONAL

## Purpose

This directory contains workflow orchestration logic using `pydantic-ai` for type-safe, declarative multi-step workflows.

## Keep This Directory If

Your Ring 0 MVP needs:

- ✅ **Multi-step workflows** with branching logic
- ✅ **Complex dependencies** between workflow steps
- ✅ **Dynamic routing** based on runtime conditions
- ✅ **Type-safe workflow definitions** validated at parse time
- ✅ **Inspectable orchestration** for debugging and visualization

## Delete This Directory If

Your Ring 0 MVP has:

- ❌ **Single agent** with no workflow orchestration
- ❌ **Simple linear flow** (step 1 → step 2 → step 3)
- ❌ **No branching** or conditional routing needed

## What's Provided

### `definitions.py`
- `GraphNode`: Atomic unit representing a workflow step
- `WorkflowGraph`: Declarative workflow definition with entrypoint and nodes
- `route()` method: Navigate the graph by node ID

### `graph_agent.py`
- Pydantic AI agent for graph-based orchestration
- Typed dependencies (`GraphDependencies`)
- Structured output (`GraphNode`)
- Tool registration for graph navigation

## Example Usage

```python
from atlas-chat.graphs import (
    WorkflowGraph,
    GraphNode,
    build_graph_agent,
    GraphDependencies
)

# Define workflow declaratively
workflow = WorkflowGraph(
    name="research_workflow",
    entrypoint="query",
    nodes=[
        GraphNode(
            id="query",
            description="Query knowledge base",
            service="deepsearch_service",
            next=["analyze"]
        ),
        GraphNode(
            id="analyze",
            description="Analyze results",
            service="analysis_service",
            next=["summarize"]
        ),
        GraphNode(
            id="summarize",
            description="Generate summary",
            service="summary_service"
        ),
    ],
)

# Execute with pydantic-ai agent
agent = build_graph_agent()
result = agent.run_sync(
    "Navigate to next node",
    deps=GraphDependencies(graph=workflow, current_node="query")
)
```

## When to Add This in Ring 0

**Add immediately if**:
- Your core value proposition involves multi-step orchestration
- You're building a workflow engine or pipeline system
- Branching logic is fundamental to your MVP

**Defer to Ring 1+ if**:
- You can ship Ring 0 with a linear flow
- Orchestration complexity isn't core to initial value
- You're still discovering the workflow structure

## Alternatives for Simple Cases

For linear workflows, consider:

```python
# Simple function composition (no graphs needed)
def simple_workflow(input_data: str) -> dict:
    step1_result = query_service(input_data)
    step2_result = analyze_service(step1_result)
    return summarize_service(step2_result)
```

Only reach for graph orchestration when you have **proven need** for:
- Branching/conditional logic
- Dynamic routing
- Workflow reusability
- Complex dependencies

## Architecture Notes

- **Declarative**: Workflows defined as data (inspectable, serializable)
- **Type-safe**: Pydantic validation at definition time
- **Testable**: Mock individual nodes, test routing logic independently
- **Observable**: Easy to add logging, metrics at node transitions

## See Also

- `SCAFFOLD_GUIDE.md` - Full decision tree for optional components
- `CLAUDE.md` - Ring-based development philosophy
- [Pydantic AI Docs](https://github.com/pydantic/pydantic-ai) - Framework documentation
