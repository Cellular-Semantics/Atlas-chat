"""The corpus on disk, read through the store's own API.

Real material, not a fixture: what these assert is that a store assembled by
the setup steps is readable by the code that has to consume it, and that its
prose pointers resolve to text rather than to nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from atlas_chat.services.supplement_store import load_manifest

pytestmark = pytest.mark.integration


def _manifests(store: Path) -> list[Path]:
    return sorted(store.glob("papers/*/manifest.json"))


def test_the_store_holds_manifests(reproductive_store: Path) -> None:
    assert _manifests(reproductive_store), f"no manifests under {reproductive_store}"


def test_every_manifest_names_the_paper_it_describes(reproductive_store: Path) -> None:
    for path in _manifests(reproductive_store):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assert (manifest.get("paper") or {}).get("doi"), f"{path} names no DOI"


def test_manifests_load_through_the_stores_own_api(reproductive_store: Path) -> None:
    """A manifest that only parses as JSON is not the same as one the store can
    find: the lookup is by DOI, through a slug the store computes itself."""
    for path in _manifests(reproductive_store):
        doi = json.loads(path.read_text(encoding="utf-8"))["paper"]["doi"]
        assert load_manifest(reproductive_store, doi) is not None, f"{doi} not findable"


def test_prose_marked_as_folding_in_resolves_to_text_on_disk(reproductive_store: Path) -> None:
    """A pointer that folds in but whose text is missing would be read as a
    paper with nothing to say, rather than as an extraction that failed."""
    unresolved = []
    for path in _manifests(reproductive_store):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for pointer in manifest.get("prose") or []:
            if not pointer.get("folds_in"):
                continue
            text_file = pointer.get("text_file")
            if not text_file or not (reproductive_store / text_file).is_file():
                unresolved.append(f"{manifest['paper']['doi']}: {text_file!r}")
    assert not unresolved, "prose folds in but its text is missing: " + "; ".join(unresolved)
