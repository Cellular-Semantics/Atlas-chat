"""Locating corpus material that is too large to live in the repository.

A project's supplements run to hundreds of megabytes, so they sit outside the
checkout and their location is given by ``ATLAS_CHAT_CORPUS_ROOT``. Under it,
each project is a directory holding a ``supplements`` store.

The two ways this can go wrong are told apart deliberately. A variable that is
not set means the corpus is simply not provisioned on this machine, which is
normal and skips. A variable that is set and wrong is a misconfiguration, and
failing on it is the only way anyone finds out — a run that silently reports no
supplements looks exactly like a paper that has none.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

CORPUS_ENV = "ATLAS_CHAT_CORPUS_ROOT"


@pytest.fixture(scope="session")
def corpus_root() -> Path:
    """Root holding one directory per project."""
    raw = os.getenv(CORPUS_ENV)
    if not raw:
        pytest.skip(f"{CORPUS_ENV} is not set; corpus material is not on this machine")
    root = Path(raw).expanduser()
    if not root.is_dir():
        raise AssertionError(f"{CORPUS_ENV} points at {root}, which is not a directory")
    return root


@pytest.fixture(scope="session")
def reproductive_store(corpus_root: Path) -> Path:
    """The reproductive project's supplement store."""
    store = corpus_root / "hca_reproductive" / "supplements"
    if not store.is_dir():
        raise AssertionError(f"no supplement store at {store}")
    return store
