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

#: Names where a project directory may sit, relative to the repository root.
PROJECT_PARENTS = ("projects", "projects/test_projects")

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
        name: the project's directory name, or a path to it.
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
    for parent in PROJECT_PARENTS:
        candidate = repo_root / parent / name
        if (candidate / "cas.json").is_file():
            return candidate
    looked = ", ".join(str(repo_root / p / name) for p in PROJECT_PARENTS)
    raise ProjectNotFound(f"no cas.json for {name!r}; looked in {looked}")


def resolve(
    name: str,
    *,
    repo_root: Path | None = None,
    corpus_root: Path | None = None,
) -> ProjectPaths:
    """Everything a reading step needs, from a project's name.

    Args:
        name: the project's directory name, or a path to it.
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m atlas_chat.cli_project",
        description="Resolve a project's paths from its name.",
    )
    parser.add_argument("--project", required=True, help="project directory name, or a path to it")
    parser.add_argument("--repo-root", help="checkout to look in; default the working directory")
    parser.add_argument("--corpus-root", help=f"default {CORPUS_ENV}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        paths = resolve(
            args.project,
            repo_root=Path(args.repo_root) if args.repo_root else None,
            corpus_root=Path(args.corpus_root) if args.corpus_root else None,
        )
    except ProjectNotFound as exc:
        print(str(exc))
        return 2
    print(json.dumps(paths.to_dict(), indent=2))
    return 0
