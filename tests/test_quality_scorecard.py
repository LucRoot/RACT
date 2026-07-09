from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path

from rootact.quality_scorecard import QualityScorecard, Verdict, _ROOT_KNOT


def test_compute_score_nonempty_plan():
    scorecard = QualityScorecard()
    plan = type(
        "Plan",
        (),
        {
            "assumption": "test assumption",
            "confidence": 0.8,
            "steps": [
                type(
                    "Step",
                    (),
                    {
                        "action": "write_file",
                        "provider_hint": "local_io",
                        "expected_artifact": "out.txt",
                    },
                )()
            ],
        },
    )()
    score = scorecard.compute_score(plan)
    # Expected: 0.8 * 1 / (1+1) = 0.4
    assert score == 0.4


def test_compute_score_empty_steps():
    scorecard = QualityScorecard()
    plan = type(
        "Plan", (), {"assumption": "no steps", "confidence": 0.9, "steps": []}
    )()
    score = scorecard.compute_score(plan)
    assert score == 0.0


def test_record_and_get_scores(tmp_path: Path):
    scorecard = QualityScorecard()
    plan1 = type(
        "Plan",
        (),
        {
            "assumption": "first",
            "confidence": 0.5,
            "steps": [
                type(
                    "Step",
                    (),
                    {"action": "a", "provider_hint": "b", "expected_artifact": "c"},
                )()
            ],
        },
    )()
    plan2 = type(
        "Plan",
        (),
        {
            "assumption": "second",
            "confidence": 0.6,
            "steps": [
                type(
                    "Step",
                    (),
                    {"action": "x", "provider_hint": "y", "expected_artifact": "z"},
                )(),
                type(
                    "Step",
                    (),
                    {"action": "y", "provider_hint": "z", "expected_artifact": "w"},
                )(),
            ],
        },
    )()
    scorecard.record_score(plan1)
    scorecard.record_score(plan2)
    scores = scorecard.get_scores()
    assert len(scores) == 2
    # Verify that the recorded scores match the computed ones
    assert scores[0]["score"] == 0.25  # 0.5 * 1 / (1+1)
    assert abs(scores[1]["score"] - 0.4) < 1e-9  # 0.6 * 2 / (1+2) = 0.4


def test_clear_resets_state():
    scorecard = QualityScorecard()
    plan = type(
        "Plan",
        (),
        {
            "assumption": "test",
            "confidence": 1.0,
            "steps": [
                type(
                    "Step",
                    (),
                    {"action": "a", "provider_hint": "b", "expected_artifact": "c"},
                )()
            ],
        },
    )()
    scorecard.record_score(plan)
    assert bool(scorecard) is True
    scorecard.clear()
    assert len(scorecard) == 0
    assert not scorecard


def test_write_and_read_json_file(tmp_path: Path):
    scorecard = QualityScorecard()
    sample_data = [{"score": 0.75}]
    scorecard._records = sample_data
    file_path = tmp_path / "scores.json"
    scorecard.write_to_file(str(file_path))
    new_scorecard = QualityScorecard()
    new_scorecard.read_from_file(str(file_path))
    assert new_scorecard.get_scores() == sample_data


def test_root_knot_is_defined_at_module_scope():
    import rootact.quality_scorecard as mod

    assert hasattr(mod, "_ROOT_KNOT")
    assert mod._ROOT_KNOT is _ROOT_KNOT


def test_verdict_all_passes_reaches_threshold():
    scorecard = QualityScorecard()
    verdict = Verdict(
        build_passes=True,
        tests_pass=True,
        lint_clean=True,
        imports_resolve=True,
        diff_minimal=True,
        no_secrets=True,
        net_entropy_change=-1.0,
        error_mask_count=0,
        duplication_similarity=0.0,
        gravity_adherence=1.0,
        mutation_score=100.0,
    )
    result = scorecard.score_verdict(verdict)
    assert result["passed"] is True
    assert result["total"] == 100.0


def test_mutation_score_scaled_to_weight():
    scorecard = QualityScorecard()
    verdict = Verdict(
        build_passes=True,
        tests_pass=True,
        lint_clean=True,
        imports_resolve=True,
        diff_minimal=True,
        no_secrets=True,
        net_entropy_change=0.0,
        error_mask_count=0,
        duplication_similarity=0.0,
        gravity_adherence=1.0,
        mutation_score=50.0,
    )
    result = scorecard.score_verdict(verdict)
    assert result["signals"]["mutation_score"] == 5.0


def test_verdict_failing_tests_fails():
    scorecard = QualityScorecard()
    verdict = Verdict(
        build_passes=True,
        tests_pass=False,
        lint_clean=True,
        imports_resolve=True,
        diff_minimal=True,
        no_secrets=True,
        net_entropy_change=0.0,
        error_mask_count=0,
        duplication_similarity=0.0,
        gravity_adherence=1.0,
    )
    result = scorecard.score_verdict(verdict)
    assert result["passed"] is False
    assert result["signals"]["tests_pass"] == 0.0


def test_deletion_bonus_capped_at_weight():
    scorecard = QualityScorecard()
    verdict = Verdict(
        build_passes=True,
        tests_pass=True,
        lint_clean=True,
        imports_resolve=True,
        diff_minimal=True,
        no_secrets=True,
        net_entropy_change=-5.0,
        error_mask_count=0,
        duplication_similarity=0.0,
        gravity_adherence=1.0,
    )
    result = scorecard.score_verdict(verdict)
    assert result["signals"]["net_entropy_change"] == 10.0


def test_error_mask_penalty_capped():
    scorecard = QualityScorecard()
    verdict = Verdict(
        build_passes=True,
        tests_pass=True,
        lint_clean=True,
        imports_resolve=True,
        diff_minimal=True,
        no_secrets=True,
        net_entropy_change=0.0,
        error_mask_count=10,
        duplication_similarity=0.0,
        gravity_adherence=1.0,
    )
    result = scorecard.score_verdict(verdict)
    assert result["signals"]["error_mask_patterns"] == -30.0


def test_duplication_penalty_scaled():
    scorecard = QualityScorecard()
    verdict = Verdict(
        build_passes=True,
        tests_pass=True,
        lint_clean=True,
        imports_resolve=True,
        diff_minimal=True,
        no_secrets=True,
        net_entropy_change=0.0,
        error_mask_count=0,
        duplication_similarity=0.5,
        gravity_adherence=1.0,
    )
    result = scorecard.score_verdict(verdict)
    assert result["signals"]["duplication_guard"] == -10.0


def test_record_verdict_stores_breakdown():
    scorecard = QualityScorecard()
    verdict = Verdict(build_passes=True, tests_pass=True)
    scorecard.record_verdict(verdict)
    scores = scorecard.get_scores()
    assert len(scores) == 1
    assert "signals" in scores[0]
    assert "total" in scores[0]


# RACT 0.1.0 - Initial Public Release
