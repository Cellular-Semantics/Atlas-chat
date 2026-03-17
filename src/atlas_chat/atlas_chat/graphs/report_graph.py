"""PydanticAI graph orchestrator for cell-type report generation.

Nodes:
  1. FetchSupplements — get supplementary material via Europe PMC
  2. ResolveName — search atlas paper + supplements for author terminology
  3. ScanSupplements + CitationTraverse — parallel, independent after name resolution
  4. SynthesizeReport — generate markdown report from all collected evidence
  5. ValidateReport — run report_checker functions
  6. On validation failure → route back to SynthesizeReport (max 2 retries)
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from cellsem_llm_client.agents.agent_connection import AgentConnection

from atlas_chat.services.atlas_paper import AtlasConfig
from atlas_chat.utils.prompt_loader import load_prompt, render_prompt
from atlas_chat.validation.report_checker import validate_report

logger = logging.getLogger(__name__)

MAX_SYNTHESIS_RETRIES = 2


# ---------------------------------------------------------------------------
# State & Dependencies
# ---------------------------------------------------------------------------

@dataclass
class ReportState:
    """Mutable state threaded through every graph node."""

    cell_type: str = ""
    depth: int = 1

    # Populated by nodes
    atlas_full_text: str = ""
    supplementary_text: str = ""
    supplementary_file_list: list[dict[str, Any]] = field(default_factory=list)

    name_resolution: dict[str, Any] = field(default_factory=dict)
    supplementary_findings: dict[str, Any] = field(default_factory=dict)
    all_summaries: list[dict[str, Any]] = field(default_factory=list)
    paper_catalogue: dict[str, Any] = field(default_factory=dict)

    report_md: str = ""
    validation_errors: list[str] = field(default_factory=list)
    synthesis_attempts: int = 0


@dataclass
class ReportDeps:
    """Immutable dependencies injected at graph start."""

    config: AtlasConfig
    agent: AgentConnection
    traversal_dir: Path
    reports_dir: Path
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Helper: run LLM call with prompt YAML
# ---------------------------------------------------------------------------

def _llm_call(
    agent: AgentConnection,
    prompt_name: str,
    schema: dict[str, Any] | None = None,
    **template_vars: str,
) -> str | Any:
    """Load a prompt YAML, render it, and call the LLM agent.

    Args:
        agent: The cellsem_llm_client agent connection.
        prompt_name: Name of the prompt YAML (without extension).
        schema: Optional JSON schema for structured output.
        **template_vars: Variables to substitute into the prompt templates.

    Returns:
        Raw string response, or validated Pydantic model if schema provided.
    """
    prompt_config = load_prompt(prompt_name)
    system_msg = render_prompt(prompt_config["system_prompt"], **template_vars)
    user_msg = render_prompt(prompt_config["user_prompt"], **template_vars)

    if schema is not None:
        return agent.query_with_schema(
            message=user_msg,
            schema=schema,
            system_message=system_msg,
        )
    return agent.query(message=user_msg, system_message=system_msg)


# ---------------------------------------------------------------------------
# Node: FetchSupplements
# ---------------------------------------------------------------------------

@dataclass
class FetchSupplements(BaseNode[ReportState, ReportDeps, str]):
    """Fetch atlas paper full text and supplementary material."""

    async def run(
        self, ctx: GraphRunContext[ReportState, ReportDeps]
    ) -> ResolveName:
        config = ctx.deps.config
        state = ctx.state

        logger.info("Fetching atlas paper and supplements for DOI: %s", config.doi)

        if ctx.deps.dry_run:
            logger.info("[DRY RUN] Skipping paper fetch")
            return ResolveName()

        # These would be called via Europe PMC / artl-mcp in a real run.
        # For the programmatic path, we use the services layer.
        # Import here to avoid hard dependency on optional HTTP libs.
        try:
            from atlas_chat.services import europepmc

            ids = await asyncio.to_thread(europepmc.resolve_identifiers, config.doi)
            if ids.pmcid:
                config.pmcid = ids.pmcid
            if ids.corpus_id:
                config.corpus_id = ids.corpus_id

            state.atlas_full_text = await asyncio.to_thread(
                europepmc.get_full_text, config.doi
            )
            state.supplementary_text = await asyncio.to_thread(
                europepmc.get_supplementary_text, config.pmcid or ""
            )
        except (ImportError, Exception) as exc:
            logger.warning("Could not fetch paper data: %s", exc)

        return ResolveName()


# ---------------------------------------------------------------------------
# Node: ResolveName
# ---------------------------------------------------------------------------

@dataclass
class ResolveName(BaseNode[ReportState, ReportDeps, str]):
    """Resolve how the atlas authors refer to this cell type."""

    async def run(
        self, ctx: GraphRunContext[ReportState, ReportDeps]
    ) -> FanOut:
        config = ctx.deps.config
        state = ctx.state
        ann = config.get_annotation(state.cell_type)
        scope = ann["scope"] if ann else "unknown"
        granularity = ann["granularity"] if ann else "unknown"

        logger.info("Resolving name for: %s", state.cell_type)

        if ctx.deps.dry_run:
            state.name_resolution = {
                "label": state.cell_type,
                "resolved_names": [state.cell_type],
                "scope": scope,
                "tissue_context": "",
                "confidence": "dry_run",
            }
            return FanOut()

        response = await asyncio.to_thread(
            _llm_call,
            ctx.deps.agent,
            "name_resolver",
            label=state.cell_type,
            scope=scope,
            granularity=granularity,
            doi=config.doi,
            title=config.title,
            supplementary_text=state.supplementary_text[:5000],
            atlas_text=state.atlas_full_text[:8000],
        )

        try:
            state.name_resolution = json.loads(response) if isinstance(response, str) else response.model_dump()
        except (json.JSONDecodeError, AttributeError):
            state.name_resolution = {
                "label": state.cell_type,
                "resolved_names": [state.cell_type],
                "scope": scope,
                "tissue_context": "",
                "confidence": "low",
                "evidence": f"Raw LLM response: {str(response)[:200]}",
            }

        # Save intermediate
        out_path = ctx.deps.traversal_dir / "name_resolution.json"
        out_path.write_text(json.dumps(state.name_resolution, indent=2))
        logger.info("Name resolution saved to %s", out_path)

        return FanOut()


# ---------------------------------------------------------------------------
# Node: FanOut — runs ScanSupplements + CitationTraverse in parallel
# ---------------------------------------------------------------------------

@dataclass
class FanOut(BaseNode[ReportState, ReportDeps, str]):
    """Fan-out node: runs supplement scanning and citation traversal in parallel."""

    async def run(
        self, ctx: GraphRunContext[ReportState, ReportDeps]
    ) -> SynthesizeReport:
        scan_task = asyncio.create_task(self._scan_supplements(ctx))
        cite_task = asyncio.create_task(self._citation_traverse(ctx))
        await asyncio.gather(scan_task, cite_task)
        return SynthesizeReport()

    async def _scan_supplements(
        self, ctx: GraphRunContext[ReportState, ReportDeps]
    ) -> None:
        state = ctx.state
        config = ctx.deps.config

        logger.info("Scanning supplementary material for: %s", state.cell_type)

        if ctx.deps.dry_run:
            state.supplementary_findings = {"markers": [], "other_findings": [], "evidence_quotes": []}
            return

        resolved_names = state.name_resolution.get("resolved_names", [state.cell_type])

        response = await asyncio.to_thread(
            _llm_call,
            ctx.deps.agent,
            "supplementary_scanner",
            label=state.cell_type,
            resolved_names=json.dumps(resolved_names),
            scope=state.name_resolution.get("scope", "unknown"),
            pmcid=config.pmcid or "",
            supplementary_text=state.supplementary_text[:15000],
        )

        try:
            state.supplementary_findings = (
                json.loads(response) if isinstance(response, str) else response.model_dump()
            )
        except (json.JSONDecodeError, AttributeError):
            state.supplementary_findings = {"markers": [], "other_findings": [], "evidence_quotes": []}

        out_path = ctx.deps.traversal_dir / "supplementary_findings.json"
        out_path.write_text(json.dumps(state.supplementary_findings, indent=2))

    async def _citation_traverse(
        self, ctx: GraphRunContext[ReportState, ReportDeps]
    ) -> None:
        """Run citation traversal via ASTA snippet search.

        This is the programmatic equivalent of the citation-traverse Claude Code
        skill. It calls Semantic Scholar snippet search and follows references
        to the configured depth.
        """
        state = ctx.state
        config = ctx.deps.config

        logger.info("Citation traversal for: %s (depth=%d)", state.cell_type, state.depth)

        if ctx.deps.dry_run:
            state.all_summaries = []
            state.paper_catalogue = {}
            return

        # Build query from resolved name + scope + tissue
        resolved = state.name_resolution.get("resolved_names", [state.cell_type])
        tissue = state.name_resolution.get("tissue_context", "")
        scope = state.name_resolution.get("scope", "")
        query = f"{state.cell_type} {' '.join(resolved)} {scope} {tissue}: location, structure, function, markers"

        # Seed paper ID
        seed_id = config.corpus_id or f"DOI:{config.doi}"

        try:
            from atlas_chat.services import citation_traverser

            summaries, catalogue = await asyncio.to_thread(
                citation_traverser.traverse,
                query=query,
                seed_ids=[seed_id],
                depth=state.depth,
                output_dir=ctx.deps.traversal_dir,
            )
            state.all_summaries = summaries
            state.paper_catalogue = catalogue
        except (ImportError, Exception) as exc:
            logger.warning("Citation traversal failed: %s", exc)
            state.all_summaries = []
            state.paper_catalogue = {}

        # Save outputs
        (ctx.deps.traversal_dir / "all_summaries.json").write_text(
            json.dumps(state.all_summaries, indent=2)
        )
        (ctx.deps.traversal_dir / "paper_catalogue.json").write_text(
            json.dumps(state.paper_catalogue, indent=2)
        )


# ---------------------------------------------------------------------------
# Node: SynthesizeReport
# ---------------------------------------------------------------------------

@dataclass
class SynthesizeReport(BaseNode[ReportState, ReportDeps, str]):
    """Generate the markdown report from all collected evidence."""

    async def run(
        self, ctx: GraphRunContext[ReportState, ReportDeps]
    ) -> ValidateReport:
        state = ctx.state
        config = ctx.deps.config
        state.synthesis_attempts += 1

        logger.info(
            "Synthesizing report for %s (attempt %d)",
            state.cell_type,
            state.synthesis_attempts,
        )

        if ctx.deps.dry_run:
            state.report_md = f"# {state.cell_type}\n\n[DRY RUN — no report generated]"
            return ValidateReport()

        resolved = state.name_resolution.get("resolved_names", [state.cell_type])
        scope = state.name_resolution.get("scope", "unknown")
        tissue = state.name_resolution.get("tissue_context", "")

        # Build validation feedback if retrying
        validation_feedback = ""
        if state.validation_errors:
            validation_feedback = (
                "IMPORTANT — Your previous report had validation errors. "
                "Fix these issues:\n"
                + "\n".join(f"- {e}" for e in state.validation_errors)
            )

        response = await asyncio.to_thread(
            _llm_call,
            ctx.deps.agent,
            "report_synthesizer",
            label=state.cell_type,
            resolved_names=json.dumps(resolved),
            scope=scope,
            tissue_context=tissue,
            atlas_title=config.title,
            doi=config.doi,
            name_resolution_json=json.dumps(state.name_resolution, indent=2),
            supplementary_findings_json=json.dumps(state.supplementary_findings, indent=2),
            all_summaries_json=json.dumps(state.all_summaries, indent=2),
            paper_catalogue_json=json.dumps(state.paper_catalogue, indent=2),
            validation_feedback=validation_feedback,
        )

        state.report_md = str(response)
        return ValidateReport()


# ---------------------------------------------------------------------------
# Node: ValidateReport
# ---------------------------------------------------------------------------

@dataclass
class ValidateReport(BaseNode[ReportState, ReportDeps, str]):
    """Validate the generated report against evidence files."""

    async def run(
        self, ctx: GraphRunContext[ReportState, ReportDeps]
    ) -> SynthesizeReport | SaveReport:
        state = ctx.state

        if ctx.deps.dry_run:
            return SaveReport()

        # Write report to temp location for validation
        report_path = ctx.deps.reports_dir / f"{state.cell_type}.md"
        report_path.write_text(state.report_md)

        passed, errors = validate_report(report_path, ctx.deps.traversal_dir)

        if passed:
            logger.info("Report validation passed for %s", state.cell_type)
            return SaveReport()

        state.validation_errors = errors
        logger.warning(
            "Report validation failed (attempt %d/%d): %s",
            state.synthesis_attempts,
            MAX_SYNTHESIS_RETRIES + 1,
            errors,
        )

        if state.synthesis_attempts > MAX_SYNTHESIS_RETRIES:
            logger.error("Max retries reached, saving report with warnings")
            return SaveReport()

        return SynthesizeReport()


# ---------------------------------------------------------------------------
# Node: SaveReport (terminal)
# ---------------------------------------------------------------------------

@dataclass
class SaveReport(BaseNode[ReportState, ReportDeps, str]):
    """Save the final report to disk."""

    async def run(
        self, ctx: GraphRunContext[ReportState, ReportDeps]
    ) -> End[str]:
        state = ctx.state
        report_path = ctx.deps.reports_dir / f"{state.cell_type}.md"
        report_path.write_text(state.report_md)
        logger.info("Report saved to %s", report_path)
        return End(str(report_path))


# ---------------------------------------------------------------------------
# Graph definition
# ---------------------------------------------------------------------------

report_graph = Graph(
    nodes=[
        FetchSupplements,
        ResolveName,
        FanOut,
        SynthesizeReport,
        ValidateReport,
        SaveReport,
    ],
    name="report_graph",
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_report_graph(
    config: AtlasConfig,
    cell_type: str,
    *,
    depth: int = 1,
    dry_run: bool = False,
    provider: str = "anthropic",
    model: str | None = None,
) -> str:
    """Run the full report generation graph for a single cell type.

    Args:
        config: Atlas project configuration.
        cell_type: The cell type annotation label.
        depth: Citation traversal depth (default 1, max 3).
        dry_run: If True, skip LLM calls and paper fetching.
        provider: LLM provider — ``"anthropic"``, ``"openai"``, or
            ``"litellm"``.
        model: Model identifier.  If ``None``, uses the default for
            the chosen provider.

    Returns:
        Path to the generated report file.
    """
    from atlas_chat.llm import create_agent

    agent = create_agent(provider=provider, model=model, max_tokens=4000)

    traversal_dir = config.traversal_dir(cell_type)
    reports_dir = config.reports_dir()

    state = ReportState(cell_type=cell_type, depth=min(depth, 3))
    deps = ReportDeps(
        config=config,
        agent=agent,
        traversal_dir=traversal_dir,
        reports_dir=reports_dir,
        dry_run=dry_run,
    )

    result = await report_graph.run(
        FetchSupplements(),
        state=state,
        deps=deps,
    )

    return result.output
