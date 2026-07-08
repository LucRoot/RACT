from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path

from rootact.result_logger import ResultLogger, _ROOT_KNOT


def test_log_and_get_logs():
    logger = ResultLogger()
    plan = type(
        "Plan",
        (),
        {
            "assumption": "test assumption",
            "confidence": 0.75,
            "steps": [
                type(
                    "Step",
                    (),
                    {"action": "a", "provider_hint": "b", "expected_artifact": "c"},
                )()
            ],
        },
    )()
    logger.log(plan)
    logs = logger.get_logs()
    assert len(logs) == 1
    record = logs[0]
    assert record["assumption"] == plan.assumption
    assert record["confidence"] == str(plan.confidence)
    assert record["step_count"] == str(len(plan.steps))


def test_clear_resets_state():
    logger = ResultLogger()
    logger.log(
        type("Plan", (), {"assumption": "test", "confidence": 0.5, "steps": []})()
    )
    assert bool(logger) is True
    logger.clear()
    assert len(logger) == 0
    assert not logger


def test_write_and_read_json_file(tmp_path: Path):
    logger = ResultLogger()
    sample_data = [{"assumption": "test", "confidence": "0.9"}]
    logger._records = sample_data
    file_path = tmp_path / "logs.json"
    logger.write_to_file(str(file_path))
    new_logger = ResultLogger()
    new_logger.read_from_file(str(file_path))
    assert new_logger.get_logs() == sample_data


def test_root_knot_is_defined_at_module_scope():
    # The source module must define _ROOT_KNOT exactly once at module scope.
    import rootact.result_logger as mod

    assert hasattr(mod, "_ROOT_KNOT")
    # Ensure it is the singleton we imported in the module.
    assert mod._ROOT_KNOT is _ROOT_KNOT


# RACT 0.1.0 - Initial Public Release
