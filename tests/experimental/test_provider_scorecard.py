__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

from rootact.experimental.provider_scorecard import compute_scorecard


def test_success_rate_and_total_cost():
    receipts = [
        {
            "provider": "A",
            "success": 1 if i < 8 else 0,
            "latency": 10.0 + i,
            "quality": 1.0 + i,
            "cost": 1.0 + i,
        }
        for i in range(10)
    ]
    result = compute_scorecard(receipts)
    assert "A" in result
    assert result["A"]["success_rate"] == 0.8
    assert result["A"]["total_cost"] == 55.0


def test_small_sample_excluded():
    receipts = [
        {"provider": "B", "success": 1, "latency": 10.0, "quality": 5.0, "cost": 1.0}
        for _ in range(5)
    ]
    result = compute_scorecard(receipts)
    assert "B" not in result


def test_medians():
    receipts = [
        {
            "provider": "C",
            "success": 1,
            "latency": lat,
            "quality": qual,
            "cost": 1.0,
        }
        for lat, qual in zip(
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 100.0],
            [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0],
        )
    ]
    result = compute_scorecard(receipts)
    assert "C" in result
    assert result["C"]["median_latency"] == 5.5
    assert result["C"]["median_quality"] == 55.0
