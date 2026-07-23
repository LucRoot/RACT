# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from ract.complexity_calibrator import ComplexityCalibrator, CalibrationRecord
from ract.complexity_router import ComplexityRouter


def _record(
    score: float, cost: float, tokens: float = 0.0, latency: float = 0.0
) -> dict:
    return {
        "complexity_score": score,
        "cost": cost,
        "tokens": tokens,
        "latency_ms": latency,
        "tier": "",
        "task_id": "",
    }


def test_fewer_than_three_records_returns_defaults():
    cal = ComplexityCalibrator().fit([_record(0.1, 1.0), _record(0.9, 100.0)])
    assert cal.recommend_thresholds() == ComplexityRouter.DEFAULT_THRESHOLDS


def test_small_dataset_uses_percentile_boundaries():
    records = [
        _record(0.05, 1.0),
        _record(0.10, 2.0),
        _record(0.40, 10.0),
        _record(0.80, 50.0),
        _record(0.95, 200.0),
    ]
    cal = ComplexityCalibrator().fit(records)
    thresholds = cal.recommend_thresholds()
    assert thresholds["low"] < thresholds["medium"] < thresholds["high"]


def test_clean_separation_finds_expected_boundaries():
    # Three tight clusters: cheap/low-score, medium, expensive/high-score.
    records = []
    for score in [0.05, 0.08, 0.12]:
        records.append(_record(score, 1.0))
    for score in [0.45, 0.50, 0.52]:
        records.append(_record(score, 25.0))
    for score in [0.85, 0.90, 0.95]:
        records.append(_record(score, 150.0))

    cal = ComplexityCalibrator().fit(records)
    thresholds = cal.recommend_thresholds()
    # Boundaries should sit between the clusters.
    assert 0.12 < thresholds["low"] < 0.45
    assert 0.52 < thresholds["medium"] < 0.85
    assert thresholds["high"] >= 0.95


def test_cost_proxy_prefers_explicit_cost():
    rec = CalibrationRecord.from_dict(
        {"cost": 10.0, "tokens": 100.0, "latency_ms": 1000.0}
    )
    assert ComplexityCalibrator._cost_proxy(rec) == 10.0


def test_cost_proxy_falls_back_to_tokens_then_latency():
    rec_tokens = CalibrationRecord.from_dict({"tokens": 50.0, "latency_ms": 500.0})
    assert ComplexityCalibrator._cost_proxy(rec_tokens) == 50.0
    rec_latency = CalibrationRecord.from_dict({"latency_ms": 250.0})
    assert ComplexityCalibrator._cost_proxy(rec_latency) == 250.0


def test_apply_to_router_updates_thresholds():
    records = [
        _record(0.05, 1.0),
        _record(0.10, 2.0),
        _record(0.50, 40.0),
        _record(0.90, 300.0),
    ]
    cal = ComplexityCalibrator().fit(records)
    router = ComplexityRouter(
        tiers={"local": {"endpoint": {}}},
        thresholds={"low": 0.1, "medium": 0.2, "high": 0.3},
    )
    cal.apply_to_router(router)
    assert router.thresholds == cal.recommend_thresholds()


def test_per_tier_summary_counts_all_records():
    records = [
        _record(0.05, 1.0),
        _record(0.15, 2.0),
        _record(0.60, 50.0),
        _record(0.90, 200.0),
    ]
    cal = ComplexityCalibrator().fit(records)
    summary = cal.per_tier_summary()
    total = sum(s.count for s in summary.values())
    assert total == len(records)
    assert summary["low"].count >= 1
    assert summary["high"].count >= 1


def test_fit_summary_contains_thresholds_and_summary():
    records = [
        _record(0.05, 1.0),
        _record(0.20, 5.0),
        _record(0.70, 100.0),
    ]
    cal = ComplexityCalibrator().fit(records)
    result = cal.fit_summary()
    assert "thresholds" in result
    assert "per_tier_summary" in result
    assert result["thresholds"]["low"] < result["thresholds"]["medium"]


def test_records_sorted_by_score_not_input_order():
    records = [
        _record(0.90, 100.0),
        _record(0.05, 1.0),
        _record(0.50, 25.0),
    ]
    cal = ComplexityCalibrator().fit(records)
    scores = [r.complexity_score for r in cal.records]
    assert scores == sorted(scores)


def test_empty_record_defaults():
    rec = CalibrationRecord.from_dict({})
    assert rec.complexity_score == 0.0
    assert rec.cost == 0.0
    assert rec.tokens == 0.0
    assert rec.latency_ms == 0.0


def test_calibration_record_tier_and_task_id():
    rec = CalibrationRecord.from_dict({"tier": "local", "task_id": "task-42"})
    assert rec.tier == "local"
    assert rec.task_id == "task-42"
