__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.execution_trace import execution_trace, _ROOT_KNOT
from rootact.manager import Plan, Step


def test_execution_trace_empty_plan():
    plan = Plan(assumption="test", confidence=0.5, steps=[])
    trace = execution_trace(plan)
    assert trace == []


def test_execution_trace_single_step():
    step = Step(action="search", provider_hint="code", expected_artifact="trace")
    plan = Plan(assumption="search finds trace", confidence=0.9, steps=[step])
    context = {"search": {"result": "found"}}
    trace = execution_trace(plan, context)
    assert len(trace) == 1
    entry = trace[0]
    assert entry["action"] == "search"
    assert entry["provider_hint"] == "code"
    assert entry["expected_artifact"] == "trace"
    assert entry["context_snapshot"] == {"result": "found"}


def test_execution_trace_uses_root_knot_sentinel():
    plan = Plan(assumption="empty context", confidence=0.1, steps=[])
    trace = execution_trace(plan, context=_ROOT_KNOT)
    assert trace == []

    # Ensure the sentinel is used exactly once in the module
    import rootact.execution_trace as module

    assert hasattr(module, "_ROOT_KNOT")


# RACT 0.1.0 - Initial Public Release
