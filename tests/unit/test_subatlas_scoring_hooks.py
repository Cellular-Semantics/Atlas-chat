"""PostToolUse hook regressions for the subatlas scoring outputs.

Both files are derived, so the hooks check arithmetic and cross-file agreement
rather than taste. Driven via subprocess like the other hook regressions, with the
sibling scores file written beside the plan so the cross-checks have something to
check against.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures" / "subatlas"
SCORES_HOOK = REPO_ROOT / ".claude" / "hooks" / "check_subatlas_scores.py"
PLAN_HOOK = REPO_ROOT / ".claude" / "hooks" / "check_subatlas_read_plan.py"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def _run(hook: Path, file_path: str, payload: Any) -> subprocess.CompletedProcess[str]:
    hook_input = json.dumps(
        {"tool_input": {"file_path": file_path, "content": json.dumps(payload)}}
    )
    return subprocess.run(
        [sys.executable, str(hook)],
        input=hook_input,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


@pytest.fixture
def paired(tmp_path: Path) -> Path:
    """A directory holding a valid scores file, so plan cross-checks can run."""
    shutil.copy(FIXTURES / "scores.good.json", tmp_path / "subatlas_scores.json")
    return tmp_path


# --------------------------------------------------------------------------
# check_subatlas_scores.py
# --------------------------------------------------------------------------


def test_generated_scores_pass_their_own_hook() -> None:
    result = _run(SCORES_HOOK, "projects/x/subatlas_scores.json", _load("scores.good.json"))
    assert result.returncode == 0, result.stderr


def test_scores_hook_ignores_other_files() -> None:
    assert _run(SCORES_HOOK, "projects/x/notes.txt", {"anything": 1}).returncode == 0


def test_scores_hook_catches_a_broken_ratio() -> None:
    result = _run(
        SCORES_HOOK, "projects/x/subatlas_scores.json", _load("scores.bad_arithmetic.json")
    )
    assert result.returncode == 2
    assert "SUBATLAS SCORES VALIDATION FAILED" in result.stderr
    assert "purity" in result.stderr
    assert "regenerate" in result.stderr


def test_scores_hook_catches_degraded_disagreeing_with_the_partition() -> None:
    result = _run(SCORES_HOOK, "projects/x/subatlas_scores.json", _load("scores.bad_degraded.json"))
    assert result.returncode == 2
    assert "degraded" in result.stderr


def test_scores_hook_rejects_a_share_that_could_not_have_been_computed() -> None:
    """No partition means the subatlas cell set's atlas-wide size was never known."""
    scores = _load("scores.good.json")
    scores["degraded"] = True
    scores["partition"] = {"basis": "none", "reason": "no n_cells"}
    result = _run(SCORES_HOOK, "projects/x/subatlas_scores.json", scores)
    assert result.returncode == 2
    assert "must be absent" in result.stderr


def test_scores_hook_rejects_invalid_json() -> None:
    hook_input = json.dumps(
        {"tool_input": {"file_path": "projects/x/subatlas_scores.json", "content": "{not json"}}
    )
    result = subprocess.run(
        [sys.executable, str(SCORES_HOOK)],
        input=hook_input,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 2
    assert "not valid JSON" in result.stderr


# --------------------------------------------------------------------------
# check_subatlas_read_plan.py
# --------------------------------------------------------------------------


def test_generated_plan_passes_its_own_hook(paired: Path) -> None:
    result = _run(PLAN_HOOK, str(paired / "subatlas_read_plan.json"), _load("read_plan.good.json"))
    assert result.returncode == 0, result.stderr


def test_plan_hook_ignores_other_files() -> None:
    assert _run(PLAN_HOOK, "projects/x/notes.txt", {"anything": 1}).returncode == 0


def test_plan_hook_catches_a_question_that_does_not_trace_to_the_scores(
    paired: Path,
) -> None:
    result = _run(
        PLAN_HOOK,
        str(paired / "subatlas_read_plan.json"),
        _load("read_plan.bad_untraceable.json"),
    )
    assert result.returncode == 2
    assert "disagrees with subatlas_scores.json" in result.stderr


def test_plan_hook_catches_a_synonym_claim_with_no_matched_synonym(paired: Path) -> None:
    result = _run(
        PLAN_HOOK, str(paired / "subatlas_read_plan.json"), _load("read_plan.bad_synonym.json")
    )
    assert result.returncode == 2
    assert "matched_synonym" in result.stderr


def test_plan_hook_catches_a_synonym_crossing_a_marker_sign(paired: Path) -> None:
    plan = _load("read_plan.good.json")
    for paper in plan["papers"]:
        for question in paper["questions"]:
            for ref in question["atlas_cell_sets"]:
                if ref.get("matched_synonym"):
                    ref["matched_synonym"] = ref["matched_synonym"] + "+"
    result = _run(PLAN_HOOK, str(paired / "subatlas_read_plan.json"), plan)
    assert result.returncode == 2
    assert "sign-safe" in result.stderr


def test_plan_hook_catches_a_coarser_claimant_that_should_have_been_dropped(
    paired: Path,
) -> None:
    plan = _load("read_plan.good.json")
    question = plan["papers"][0]["questions"][0]
    ref = dict(question["atlas_cell_sets"][0])
    ref["cell_set_accession"] = "P"
    ref["cell_label"] = "parent"
    ref["labelset"] = "L1"
    ref.pop("nested_under", None)
    question["atlas_cell_sets"][0]["nested_under"] = "P"
    question["atlas_cell_sets"].append(ref)
    result = _run(PLAN_HOOK, str(paired / "subatlas_read_plan.json"), plan)
    assert result.returncode == 2
    assert "should have been dropped" in result.stderr


def test_plan_hook_catches_nested_under_pointing_outside_the_question(paired: Path) -> None:
    plan = _load("read_plan.good.json")
    plan["papers"][0]["questions"][0]["atlas_cell_sets"][0]["nested_under"] = "NOWHERE"
    result = _run(PLAN_HOOK, str(paired / "subatlas_read_plan.json"), plan)
    assert result.returncode == 2
    assert "not an atlas cell set" in result.stderr


def test_plan_hook_catches_purity_only_on_a_run_that_had_a_partition(paired: Path) -> None:
    plan = _load("read_plan.good.json")
    plan["papers"][0]["questions"][0]["included_by"] = "purity_only"
    result = _run(PLAN_HOOK, str(paired / "subatlas_read_plan.json"), plan)
    assert result.returncode == 2
    assert "purity_only" in result.stderr


def test_plan_hook_skips_cross_checks_when_the_scores_are_absent(tmp_path: Path) -> None:
    """A missing sibling is a tolerated gap, not a failure."""
    result = _run(
        PLAN_HOOK, str(tmp_path / "subatlas_read_plan.json"), _load("read_plan.good.json")
    )
    assert result.returncode == 0, result.stderr
