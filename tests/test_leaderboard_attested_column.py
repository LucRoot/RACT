"""Tests for the leaderboard ``attested_pass_rate`` column and the
``evals/antilazy/`` corpus shape (ALM module_07).

Five tests per the module_07 spec:

1. ``test_attested_pass_rate_computed_from_rootknot_signatures``
2. ``test_leaderboard_regeneration_idempotent``
3. ``test_leaderboard_includes_new_columns``
4. ``test_antilazy_corpus_has_10_cases``
5. ``test_companion_matrix_regeneration_idempotent``
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.leaderboard.update import (
    AttestationSummary,
    compute_attestation_summaries,
    update,
)
from evals.leaderboard.update_companion_matrix import (
    regenerate_companion_matrix,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _write_rootknot(
    root: Path,
    subdir: str,
    *,
    provider: str,
    generator_valid: bool = True,
    environment_valid: bool = True,
    antilazy_valid: bool = True,
    reversal_taint: str = "clean",
    gates_all_pass: bool = True,
) -> None:
    """Write a synthetic rootknot sidecar under ``root/subdir/rootknot.json``."""
    (root / subdir).mkdir(parents=True, exist_ok=True)
    if gates_all_pass:
        gate_results = [
            {"name": f"G{i}", "passed": True, "handshake_id": None} for i in range(1, 9)
        ]
    else:
        gate_results = [
            {"name": "G1", "passed": True, "handshake_id": None},
            {"name": "G2", "passed": False, "handshake_id": None},
        ]
    payload = {
        "provider": provider,
        "signatures": {
            "generator_valid": generator_valid,
            "environment_valid": environment_valid,
            "antilazy_valid": antilazy_valid,
        },
        "reversal_taint": reversal_taint,
        "gate_results": gate_results,
    }
    (root / subdir / "rootknot.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_polyglot_report(
    root: Path,
    *,
    provider: str,
    passed: int = 5,
    failed: int = 3,
    skipped: int = 2,
    subset_size: int = 10,
    generated_on: str = "2026-07-26",
) -> None:
    """Write a synthetic polyglot report JSON under ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "corpus": "aider_polyglot",
        "provider": provider,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "subset_size": subset_size,
        "pass_rate": passed / max(1, subset_size),
        "generated_on": generated_on,
        "results": [],
    }
    filename = f"{generated_on}-polyglot-{provider}.json"
    (root / filename).write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1 — attested_pass_rate arithmetic
# ---------------------------------------------------------------------------


def test_attested_pass_rate_computed_from_rootknot_signatures(
    tmp_path: Path,
) -> None:
    """7 clean + 3 partial rootknots produce attested_pass_rate == 0.7."""
    runs_root = tmp_path / "runs"
    for i in range(7):
        _write_rootknot(
            runs_root,
            f"polyglot_antilazy/run-{i:02d}",
            provider="testprov",
        )
    # 3 with partial issues — different failure kinds, all should
    # count as un-attested.
    _write_rootknot(
        runs_root,
        "polyglot_antilazy/run-07",
        provider="testprov",
        antilazy_valid=False,
    )
    _write_rootknot(
        runs_root,
        "polyglot_antilazy/run-08",
        provider="testprov",
        reversal_taint="partial",
    )
    _write_rootknot(
        runs_root,
        "polyglot_antilazy/run-09",
        provider="testprov",
        gates_all_pass=False,
    )

    summaries = compute_attestation_summaries(runs_root)
    assert "testprov" in summaries
    summary: AttestationSummary = summaries["testprov"]
    assert summary.total_runs_with_rootknot == 10
    assert summary.attested_runs == 7
    assert summary.total_runs_no_rootknot == 0
    assert summary.attested_runs / summary.total_runs_with_rootknot == pytest.approx(
        0.7
    )


# ---------------------------------------------------------------------------
# Test 2 — leaderboard regeneration is idempotent
# ---------------------------------------------------------------------------


def test_leaderboard_regeneration_idempotent(tmp_path: Path) -> None:
    """Running ``update`` twice with unchanged inputs yields no second write."""
    runs_root = tmp_path / "runs"
    _write_polyglot_report(runs_root, provider="fakeidempotent")
    _write_rootknot(
        runs_root,
        "polyglot_antilazy/run-00",
        provider="fakeidempotent",
    )

    leaderboard = tmp_path / "LEADERBOARD.md"
    conformance_results = tmp_path / "conformance" / "RESULTS.md"
    security_results = tmp_path / "security" / "RESULTS.md"

    first = update(
        leaderboard_path=leaderboard,
        runs_root=runs_root,
        conformance_results=conformance_results,
        security_results=security_results,
    )
    assert first.written is True

    first_bytes = leaderboard.read_bytes()

    second = update(
        leaderboard_path=leaderboard,
        runs_root=runs_root,
        conformance_results=conformance_results,
        security_results=security_results,
    )
    assert second.written is False, (
        "Second regeneration must be a no-op (bytes must not change)."
    )
    assert leaderboard.read_bytes() == first_bytes


# ---------------------------------------------------------------------------
# Test 3 — leaderboard includes the new columns
# ---------------------------------------------------------------------------


def test_leaderboard_includes_new_columns(tmp_path: Path) -> None:
    """Post-regeneration the leaderboard has the three new columns."""
    runs_root = tmp_path / "runs"
    _write_polyglot_report(runs_root, provider="fakecolumns")
    _write_rootknot(
        runs_root,
        "polyglot_antilazy/run-00",
        provider="fakecolumns",
    )

    leaderboard = tmp_path / "LEADERBOARD.md"
    update(
        leaderboard_path=leaderboard,
        runs_root=runs_root,
        conformance_results=tmp_path / "conformance" / "RESULTS.md",
        security_results=tmp_path / "security" / "RESULTS.md",
    )
    text = leaderboard.read_text(encoding="utf-8")
    assert "claimed_pass_rate" in text
    assert "attested_pass_rate" in text
    assert "attestation_gap" in text


# ---------------------------------------------------------------------------
# Test 4 — antilazy corpus has 10 cases with the correct shape
# ---------------------------------------------------------------------------


REQUIRED_ANTILAZY_CASES: set[str] = {
    "swe_bench_conftest_shortcut",
    "chess_hacking_grader_overwrite",
    "monkey_patched_scorer",
    "solution_leakage_git_history",
    "semantic_noop_pass_all_tests",
    "weak_assertion_insertion",
    "under_edit_missed_caller",
    "sycophantic_reversal_no_evidence",
    "sandbagging_under_effort",
    "pattern_matching_rule_like",
}


def test_antilazy_corpus_has_10_cases() -> None:
    """``evals/antilazy/`` has the 10 module_07 case directories."""
    corpus_root = REPO_ROOT / "evals" / "antilazy"
    assert corpus_root.is_dir(), (
        f"evals/antilazy/ must exist as the corpus root; got {corpus_root}"
    )
    present = {p.name for p in corpus_root.iterdir() if p.is_dir()}
    missing = REQUIRED_ANTILAZY_CASES - present
    assert not missing, f"Missing antilazy corpus cases: {sorted(missing)}"

    for case in REQUIRED_ANTILAZY_CASES:
        case_dir = corpus_root / case
        intent = case_dir / "intent.txt"
        expected = case_dir / "expected.json"
        workspace = case_dir / "workspace"
        assert intent.is_file(), f"{case}/intent.txt missing"
        assert expected.is_file(), f"{case}/expected.json missing"
        assert workspace.is_dir(), f"{case}/workspace/ missing"

        data = json.loads(expected.read_text(encoding="utf-8"))
        assert "public_source" in data, (
            f"{case}/expected.json must cite a public_source (Lateral Chain "
            f"branch A, module_07)."
        )
        assert data["public_source"], (
            f"{case}/expected.json public_source must be non-empty."
        )
        assert "gates_that_must_fire" in data, (
            f"{case}/expected.json must name the gate(s) that must fire."
        )


# ---------------------------------------------------------------------------
# Test 5 — companion matrix regeneration is idempotent
# ---------------------------------------------------------------------------


def _write_conformance_report(
    results_root: Path,
    *,
    provider: str,
    generated_on: str,
    anti_lazy: float,
    schema: float,
) -> None:
    """Write a synthetic conformance report card."""
    results_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": provider,
        "generated_on": generated_on,
        "categories": {
            "anti_lazy": {"score": anti_lazy, "passed": 0, "total": 0},
            "schema_compliance": {"score": schema, "passed": 0, "total": 0},
        },
    }
    # The regenerator parses stem via ``rsplit("-", 3)``; use the
    # ``<provider>-<yyyy>-<mm>-<dd>.json`` filename shape.
    filename = f"{provider}-{generated_on}.json"
    (results_root / filename).write_text(json.dumps(payload), encoding="utf-8")


def test_companion_matrix_regeneration_idempotent(tmp_path: Path) -> None:
    """Running ``regenerate_companion_matrix`` twice yields no second write."""
    results_root = tmp_path / "results"
    _write_conformance_report(
        results_root,
        provider="mistral",
        generated_on="2026-07-26",
        anti_lazy=0.85,
        schema=0.95,
    )
    _write_conformance_report(
        results_root,
        provider="google",
        generated_on="2026-07-26",
        anti_lazy=0.90,
        schema=0.97,
    )

    output_path = tmp_path / "COMPANION_MATRIX.md"

    changed_first, rows_first = regenerate_companion_matrix(
        results_root=results_root,
        output_path=output_path,
    )
    assert changed_first is True
    assert len(rows_first) == 2

    first_bytes = output_path.read_bytes()

    changed_second, rows_second = regenerate_companion_matrix(
        results_root=results_root,
        output_path=output_path,
    )
    assert changed_second is False, (
        "Second companion-matrix regeneration must be a no-op."
    )
    assert output_path.read_bytes() == first_bytes
    assert len(rows_second) == 2
