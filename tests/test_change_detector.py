from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path

from rootact.change_detector import ChangeDetector, _ROOT_KNOT


def test_diff_adds_and_removes():
    detector = ChangeDetector()
    old_plan = type(
        "Plan",
        (),
        {
            "assumption": "old assump",
            "confidence": 0.5,
            "steps": [
                type(
                    "Step",
                    (),
                    {
                        "action": "read_file",
                        "provider_hint": "local_io",
                        "expected_artifact": "input.txt",
                    },
                )()
            ],
        },
    )()
    new_plan = type(
        "Plan",
        (),
        {
            "assumption": "new assump",
            "confidence": 0.6,
            "steps": [
                type(
                    "Step",
                    (),
                    {
                        "action": "read_file",
                        "provider_hint": "local_io",
                        "expected_artifact": "input.txt",
                    },
                )(),
                type(
                    "Step",
                    (),
                    {
                        "action": "write_file",
                        "provider_hint": "local_io",
                        "expected_artifact": "output.txt",
                    },
                )(),
            ],
        },
    )()
    result = detector.diff(new_plan, old_plan)
    assert result["added"] == ["write_file:output.txt"]
    assert result["removed"] == []


def test_diff_empty_old_plan():
    detector = ChangeDetector()
    new_plan = type(
        "Plan",
        (),
        {
            "assumption": "only new",
            "confidence": 1.0,
            "steps": [
                type(
                    "Step",
                    (),
                    {
                        "action": "run_test",
                        "provider_hint": "pytest",
                        "expected_artifact": "report.json",
                    },
                )()
            ],
        },
    )()
    result = detector.diff(new_plan, None)
    assert set(result["added"]) == {"run_test:report.json"}
    assert result["removed"] == []


def test_diff_empty_new_plan():
    detector = ChangeDetector()
    old_plan = type(
        "Plan",
        (),
        {
            "assumption": "only old",
            "confidence": 0.8,
            "steps": [
                type(
                    "Step",
                    (),
                    {
                        "action": "delete_file",
                        "provider_hint": "local_io",
                        "expected_artifact": "temp.tmp",
                    },
                )()
            ],
        },
    )()
    result = detector.diff(
        type("Plan", (), {"assumption": "", "confidence": 0.0, "steps": []})(), old_plan
    )
    assert result["added"] == []
    assert set(result["removed"]) == {"delete_file:temp.tmp"}


def test_root_knot_is_defined_at_module_scope():
    import rootact.change_detector as mod

    assert hasattr(mod, "_ROOT_KNOT")
    assert mod._ROOT_KNOT is _ROOT_KNOT


def test_reset_clears_state(tmp_path: Path):
    detector = ChangeDetector()
    old_plan = type(
        "Plan",
        (),
        {
            "assumption": "",
            "confidence": 0.0,
            "steps": [
                type(
                    "Step",
                    (),
                    {"action": "a", "provider_hint": "b", "expected_artifact": "c"},
                )()
            ],
        },
    )()
    detector.diff(old_plan, None)
    assert bool(detector) is True
    detector.reset()
    assert not detector


# RACT 0.1.0 - Initial Public Release
