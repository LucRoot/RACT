from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.output_formatter import OutputFormatter, _ROOT_KNOT


def test_format_plan_non_empty():
    formatter = OutputFormatter()
    plan = type(
        "Plan",
        (),
        {
            "assumption": "test assumption",
            "confidence": 0.85,
            "steps": [
                type(
                    "Step",
                    (),
                    {
                        "action": "write_file",
                        "provider_hint": "local_io",
                        "expected_artifact": "output.txt",
                    },
                )(),
                type(
                    "Step",
                    (),
                    {
                        "action": "run_test",
                        "provider_hint": "pytest",
                        "expected_artifact": "test_report.json",
                    },
                ),
            ],
        },
    )()
    result = formatter.format_plan(plan)
    assert isinstance(result, str)
    assert "test assumption" in result
    assert "write_file" in result
    assert "run_test" in result
    assert "output.txt" in result
    assert "test_report.json" in result


def test_format_plan_empty():
    formatter = OutputFormatter()
    empty_plan = type(
        "Plan", (), {"assumption": "no steps", "confidence": 1.0, "steps": []}
    )()
    result = formatter.format_plan(empty_plan)
    assert result == ""


def test_format_steps_single():
    formatter = OutputFormatter()
    step = type(
        "Step",
        (),
        {"action": "read_file", "provider_hint": "fs", "expected_artifact": "data.csv"},
    )()
    result = formatter.format_steps([step])
    assert result == "  read_file (fs) -> data.csv"


def test_format_steps_multiple():
    formatter = OutputFormatter()
    steps = [
        type(
            "Step",
            (),
            {
                "action": "download",
                "provider_hint": "http",
                "expected_artifact": "raw.zip",
            },
        ),
        type(
            "Step",
            (),
            {
                "action": "process",
                "provider_hint": "python",
                "expected_artifact": "processed.json",
            },
        ),
    ]
    result = formatter.format_steps(steps)
    assert "download" in result
    assert "process" in result
    assert "raw.zip" in result
    assert "processed.json" in result


def test_reset_indent():
    formatter = OutputFormatter()
    formatter.reset_indent()
    step = type(
        "Step",
        (),
        {"action": "test", "provider_hint": "mock", "expected_artifact": "out"},
    )()
    formatted = formatter._format_step(step)
    assert formatted.startswith("  ")  # default indent


def test_root_knot_is_defined_at_module_scope():
    import rootact.output_formatter as mod

    assert hasattr(mod, "_ROOT_KNOT")
    assert mod._ROOT_KNOT is _ROOT_KNOT
