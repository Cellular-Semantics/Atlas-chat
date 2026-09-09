"""Where a project's things are, given only its name.

Everything a reading step needs — the paper, its supplements, the annotations,
somewhere to write — is either recorded in the project's CAS+ document or falls
out of the layout. Making a caller pass all of it means making a caller know all
of it, and a path typed by hand is a path that can be typed wrongly.

So this resolves them, and says which it could not find rather than returning a
path to nothing. A project that is missing its paper is a normal state — it has
not been fetched yet — and the difference between *absent* and *not looked for*
is what a caller needs in order to do something about it.

This is glue: it knows this repository's layout, and deliberately so. The
services it resolves paths for know none of it and take paths as arguments, which
is what lets them be used anywhere.

Supplements are the one thing that may live outside the checkout, because they
run to hundreds of megabytes. ``ATLAS_CHAT_CORPUS_ROOT`` names where, and a store
inside the project is used when there is one.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Where a project directory sits, relative to the repository root. Only one,
#: deliberately: a bare name searched across several parents would resolve to
#: whichever was looked at first, and a test project quietly standing in for a
#: working atlas is not a mistake anyone would catch by reading the output.
#: A project nested under this is named with its subdirectory,
#: ``test_projects/<name>``.
PROJECTS_DIR = "projects"

#: Environment variable naming the root of out-of-checkout corpus material.
CORPUS_ENV = "ATLAS_CHAT_CORPUS_ROOT"


class ProjectNotFound(RuntimeError):
    """Raised when no project of that name has a CAS+ document."""


@dataclass
class ProjectPaths:
    """A project's locations, and what could not be found."""

    name: str
    project_dir: Path
    cas: Path
    doi: str | None = None
    title: str | None = None
    paper_text: Path | None = None
    supplement_store: Path | None = None
    traversal_output: Path | None = None
    gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "project_dir": str(self.project_dir)}
        for key in ("cas", "paper_text", "supplement_store", "traversal_output"):
            value = getattr(self, key)
            if value is not None:
                out[key] = str(value)
        for key in ("doi", "title"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        if self.gaps:
            out["gaps"] = self.gaps
        return out


def paper_slug(doi: str) -> str:
    """The directory name a paper's cached text sits under."""
    from atlas_chat.services.local_snippet_index import paper_slug as slug

    return slug(doi)


def find_project(name: str, repo_root: Path) -> Path:
    """The directory holding this project's CAS+ document.

    Args:
        name: the project's directory under ``projects``, or a path to it. A
            project filed in a subdirectory is named with it, as in
            ``test_projects/<name>``.
        repo_root: the checkout to look in.

    Returns:
        The project directory.

    Raises:
        ProjectNotFound: nowhere under the known parents has a CAS+ document by
            that name. Guessing a location would produce a path to nothing.
    """
    direct = Path(name)
    if (direct / "cas.json").is_file():
        return direct
    candidate = repo_root / PROJECTS_DIR / name
    if (candidate / "cas.json").is_file():
        return candidate

    # A name that only resolves somewhere else is worth saying out loud: the
    # alternative is a caller assuming the project is missing when it is filed
    # under a subdirectory they did not name.
    nested = sorted(
        p.parent.relative_to(repo_root / PROJECTS_DIR)
        for p in (repo_root / PROJECTS_DIR).glob(f"*/{name}/cas.json")
    )
    hint = f"; did you mean {' or '.join(str(n) for n in nested)}?" if nested else ""
    raise ProjectNotFound(f"no cas.json at {candidate}{hint}")


def resolve(
    name: str,
    *,
    repo_root: Path | None = None,
    corpus_root: Path | None = None,
) -> ProjectPaths:
    """Everything a reading step needs, from a project's name.

    Args:
        name: the project's directory under ``projects``, or a path to it.
        repo_root: the checkout. Defaults to the working directory.
        corpus_root: where out-of-checkout material lives. Defaults to
            ``ATLAS_CHAT_CORPUS_ROOT``.

    Returns:
        The paths, with a gap recorded for each thing that is not there.
    """
    root = Path(repo_root) if repo_root else Path.cwd()
    project_dir = find_project(name, root)
    cas_path = project_dir / "cas.json"
    paths = ProjectPaths(name=project_dir.name, project_dir=project_dir, cas=cas_path)

    cas = json.loads(cas_path.read_text(encoding="utf-8"))
    source = cas.get("source") or {}
    paths.doi = source.get("doi")
    paths.title = source.get("title")

    traversal = project_dir / "traversal_output"
    traversal.mkdir(parents=True, exist_ok=True)
    paths.traversal_output = traversal

    if paths.doi:
        cached = project_dir / "local_index" / "papers" / paper_slug(paths.doi) / "source"
        jats = cached / "paper.jats.xml"
        if jats.is_file():
            paths.paper_text = jats
        else:
            paths.gaps.append(f"no paper text at {jats}; fetch it before reading")
    else:
        paths.gaps.append("CAS+ records no DOI for the atlas paper")

    env_root = corpus_root or (Path(os.environ[CORPUS_ENV]) if os.getenv(CORPUS_ENV) else None)
    for candidate in (
        (Path(env_root) / project_dir.name / "supplements") if env_root else None,
        project_dir / "supplements",
    ):
        if candidate is not None and candidate.is_dir():
            paths.supplement_store = candidate
            break
    if paths.supplement_store is None:
        where = f"{CORPUS_ENV} is not set" if not env_root else f"nothing under {env_root}"
        paths.gaps.append(f"no supplement store for {project_dir.name} ({where})")

    return paths


# ------------------------------------------------------------------
# The annotation hierarchy, small enough to read
# ------------------------------------------------------------------

#: Columns of the outline, in order.
OUTLINE_COLUMNS = ("labelset", "label", "full name", "parent", "cells", "synonyms")


def _searchable(annotation: dict[str, Any]) -> str:
    parts = [annotation.get("cell_label", ""), annotation.get("cell_fullname") or ""]
    parts.extend(annotation.get("synonyms") or [])
    return " ".join(parts).lower()


def _descendants(root: str, by_parent: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    stack = list(by_parent.get(root, []))
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(by_parent.get(node.get("cell_set_accession") or "", []))
    return out


def outline(
    cas: dict[str, Any],
    *,
    labelset: str | None = None,
    match: str | None = None,
    under: str | None = None,
    synonyms: bool = False,
) -> str:
    """The annotation hierarchy as lines, without the composition that dwarfs it.

    A CAS+ document is mostly the breakdown of every descriptor over every cell,
    which says nothing about what a cell type is called or where it sits. What is
    left is small enough to read, and reading it is what lets a vague request —
    all the macrophages, only the ones at this level — be answered by judgement
    rather than by pattern.

    The parent is here because matching on text alone is not enough: a cell type's
    label need not contain the word for what it is, and its siblings' labels need
    not resemble each other. Finding a node by name and taking what sits under it
    catches those; a substring does not.

    Args:
        cas: the CAS+ document.
        labelset: keep only this level.
        match: keep annotations whose label, full name or synonyms contain this.
        under: keep everything beneath the annotation with this label.
        synonyms: include them in the output.

    Returns:
        A header line and one line per annotation, tab-separated, in document
        order. Empty where a field is absent, so the columns stay aligned.
    """
    annotations = cas.get("annotations") or []
    by_accession = {
        a.get("cell_set_accession"): a for a in annotations if a.get("cell_set_accession")
    }
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for a in annotations:
        by_parent.setdefault(a.get("parent_cell_set_accession") or "", []).append(a)

    kept = list(annotations)
    if under:
        roots = [a for a in annotations if a.get("cell_label") == under]
        wanted = {
            id(a)
            for root in roots
            for a in _descendants(root.get("cell_set_accession") or "", by_parent)
        }
        kept = [a for a in kept if id(a) in wanted]
    if labelset:
        kept = [a for a in kept if a.get("labelset") == labelset]
    if match:
        needle = match.lower()
        kept = [a for a in kept if needle in _searchable(a)]

    columns = OUTLINE_COLUMNS if synonyms else OUTLINE_COLUMNS[:-1]
    lines = ["\t".join(columns)]
    for a in kept:
        parent = by_accession.get(a.get("parent_cell_set_accession") or "")
        fullname = a.get("cell_fullname") or ""
        row = [
            a.get("labelset", ""),
            a.get("cell_label", ""),
            "" if fullname == a.get("cell_label") else fullname,
            parent.get("cell_label", "") if parent else "",
            str(a.get("n_cells", "")),
        ]
        if synonyms:
            row.append(";".join(a.get("synonyms") or []))
        lines.append("\t".join(row))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m atlas_chat.cli_project",
        description="A project's paths, and its annotation hierarchy.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--project",
        required=True,
        help="project directory under projects/, e.g. test_projects/<name>, or a path",
    )
    common.add_argument("--repo-root", help="checkout to look in; default the working directory")

    paths = sub.add_parser("paths", parents=[common], help="where the project's things are")
    paths.add_argument("--corpus-root", help=f"default {CORPUS_ENV}")

    out = sub.add_parser("outline", parents=[common], help="the annotation hierarchy")
    out.add_argument("--labelset", help="keep only this level")
    out.add_argument("--match", help="keep annotations whose label, full name or synonyms match")
    out.add_argument("--under", help="keep everything beneath this annotation")
    out.add_argument("--synonyms", action="store_true", help="include synonyms")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.repo_root) if args.repo_root else None
    try:
        if args.command == "outline":
            project_dir = find_project(args.project, root or Path.cwd())
            cas = json.loads((project_dir / "cas.json").read_text(encoding="utf-8"))
            print(
                outline(
                    cas,
                    labelset=args.labelset,
                    match=args.match,
                    under=args.under,
                    synonyms=args.synonyms,
                )
            )
            return 0
        paths = resolve(
            args.project,
            repo_root=root,
            corpus_root=Path(args.corpus_root) if args.corpus_root else None,
        )
    except ProjectNotFound as exc:
        print(str(exc))
        return 2
    print(json.dumps(paths.to_dict(), indent=2))
    return 0
