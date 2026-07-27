"""module_07 (v0.4.0) — eval runner shape tests.

Verifies the four DoD leaves:

- Polyglot runner produces unified-diff output.
- Polyglot runner runs two attempts with test feedback when the first
  attempt fails.
- SWE-bench runner produces a git patch.
- SWE-bench runner applies the patch and runs the instance's hidden
  test set (`FAIL_TO_PASS` + `PASS_TO_PASS`).

The tests dispatch against the shipped fixture provider streams
(schema v2 per `docs/EVENTS.md`) so the harness is exercised
end-to-end without live-provider or upstream-registry access.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.polyglot.runner import RunConfig as PolyRunConfig
from evals.polyglot.runner import run_problem as run_polyglot_problem
from evals.swe_bench_lite.runner import RunConfig as SwebRunConfig
from evals.swe_bench_lite.runner import run_instance as run_swebench_instance


REPO_ROOT = Path(__file__).resolve().parent.parent
POLYGLOT_FIXTURES = REPO_ROOT / "evals" / "fixtures" / "providers" / "aider_polyglot"
SWEBENCH_FIXTURES = REPO_ROOT / "evals" / "fixtures" / "providers" / "swebench_lite"


# ---------------------------------------------------------------------------
# Polyglot: unified diff + two-attempts-with-feedback
# ---------------------------------------------------------------------------


def test_polyglot_runner_produces_unified_diff(tmp_path: Path) -> None:
    """First-attempt-pass fixture: exactly one attempt, unified diff present."""
    result = run_polyglot_problem(
        "acronym",
        PolyRunConfig(
            workspace=tmp_path,
            subset_path=REPO_ROOT / "evals" / "polyglot" / "subset.json",
            provider="fake",
            fixtures_root=POLYGLOT_FIXTURES,
        ),
    )
    assert result.outcome == "passed", result
    assert len(result.attempts) == 1
    assert result.attempts[0].hidden_tests_passed is True
    diff = result.attempts[0].unified_diff
    assert diff.startswith("--- a/"), "Aider Polyglot output must be a unified diff"
    assert "+++ b/" in diff
    assert len(result.transaction_step_ids_hex) == 1


def test_polyglot_runner_two_attempts_with_feedback(tmp_path: Path) -> None:
    """Fail-then-pass fixture: two attempts, feedback carries into attempt 2."""
    result = run_polyglot_problem(
        "allergies",
        PolyRunConfig(
            workspace=tmp_path,
            subset_path=REPO_ROOT / "evals" / "polyglot" / "subset.json",
            provider="fake",
            fixtures_root=POLYGLOT_FIXTURES,
        ),
    )
    assert result.outcome == "passed", result
    assert len(result.attempts) == 2
    assert result.attempts[0].hidden_tests_passed is False
    assert result.attempts[0].feedback != "", "attempt 1 failure must produce feedback"
    assert result.attempts[1].hidden_tests_passed is True
    # Every attempt opens its own step transaction (module_02).
    assert len(result.transaction_step_ids_hex) == 2
    assert result.transaction_step_ids_hex[0] != result.transaction_step_ids_hex[1]


def test_polyglot_runner_skips_when_fixture_missing(tmp_path: Path) -> None:
    """No fixture on disk yields SKIPPED with a specific reason (Lateral A)."""
    result = run_polyglot_problem(
        "clock",  # no clock.jsonl fixture shipped
        PolyRunConfig(
            workspace=tmp_path,
            subset_path=REPO_ROOT / "evals" / "polyglot" / "subset.json",
            provider="fake",
            fixtures_root=POLYGLOT_FIXTURES,
        ),
    )
    assert result.outcome == "skipped"
    assert "fixture-not-found" in result.skip_reason


# ---------------------------------------------------------------------------
# SWE-bench Lite: git patch + fail_to_pass/pass_to_pass hidden test set
# ---------------------------------------------------------------------------


def test_swebench_runner_produces_git_patch(tmp_path: Path) -> None:
    """The runner extracts a git patch from the fixture response event."""
    instance = {
        "instance_id": "django__django-11099",
        "repo": "django/django",
        "docker_image": "docker.io/swebench/sweb.eval.x86_64.django__django-11099:latest",
    }
    result = run_swebench_instance(
        instance,
        SwebRunConfig(
            workspace=tmp_path,
            instances_path=REPO_ROOT / "evals" / "swe_bench_lite" / "instances.json",
            provider="fake",
            fixtures_root=SWEBENCH_FIXTURES,
        ),
    )
    assert result.outcome == "passed", result
    assert result.attempt is not None
    patch = result.attempt.git_patch
    assert patch.startswith("diff --git"), "SWE-bench Lite output must be a git patch"
    assert "---" in patch and "+++" in patch


def test_swebench_runner_applies_patch_and_runs_hidden_tests(tmp_path: Path) -> None:
    """Pass requires both FAIL_TO_PASS and PASS_TO_PASS test sets green."""
    instance = {
        "instance_id": "django__django-11099",
        "repo": "django/django",
        "docker_image": "docker.io/swebench/sweb.eval.x86_64.django__django-11099:latest",
    }
    result = run_swebench_instance(
        instance,
        SwebRunConfig(
            workspace=tmp_path,
            instances_path=REPO_ROOT / "evals" / "swe_bench_lite" / "instances.json",
            provider="fake",
            fixtures_root=SWEBENCH_FIXTURES,
        ),
    )
    assert result.outcome == "passed", result
    assert result.attempt is not None
    assert result.attempt.fail_to_pass_ok is True
    assert result.attempt.pass_to_pass_ok is True
    # Transaction id is populated — the module_02 substrate is exercised.
    assert result.transaction_step_id_hex


def test_swebench_runner_skips_when_fixture_missing(tmp_path: Path) -> None:
    """No fixture on disk yields SKIPPED with a specific reason (Lateral A)."""
    instance = {
        "instance_id": "sympy__sympy-13480",  # no fixture shipped for this one
        "repo": "sympy/sympy",
        "docker_image": "docker.io/swebench/sweb.eval.x86_64.sympy__sympy-13480:latest",
    }
    result = run_swebench_instance(
        instance,
        SwebRunConfig(
            workspace=tmp_path,
            instances_path=REPO_ROOT / "evals" / "swe_bench_lite" / "instances.json",
            provider="fake",
            fixtures_root=SWEBENCH_FIXTURES,
        ),
    )
    assert result.outcome == "skipped"
    assert "fixture-not-found" in result.skip_reason


# ---------------------------------------------------------------------------
# Fixture-stream schema compliance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        POLYGLOT_FIXTURES / "acronym.jsonl",
        POLYGLOT_FIXTURES / "allergies.jsonl",
        SWEBENCH_FIXTURES / "django__django-11099.jsonl",
    ],
)
def test_fixture_streams_declare_schema_v2(path: Path) -> None:
    """Every fixture header declares docs/EVENTS.md schema_version 2 (module_06)."""
    import json as _json

    first = next(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    header = _json.loads(first)
    assert header.get("schema_version") == "2", (
        f"{path.name} must declare schema_version 2 per module_06"
    )


# RACT 0.4.0
