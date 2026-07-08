__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.dependency_graph import DependencyGraph
from rootact.manager import Plan, Step


def test_dependency_graph_infers_dependencies_from_action_text():
    graph = DependencyGraph()
    step1 = Step(
        action="download", provider_hint="s3://bucket", expected_artifact="raw_data"
    )
    step2 = Step(
        action="process raw_data into usable form",
        provider_hint="",
        expected_artifact="processed_data",
    )
    plan = Plan(assumption="raw_data exists", confidence=0.9, steps=[step1, step2])
    graph.add_plan(plan)
    assert graph.get_dependencies("processed_data") == {"raw_data"}
    assert graph.get_dependents("raw_data") == {"processed_data"}


def test_dependency_graph_no_false_dependencies_when_action_does_not_reference_artifact():
    graph = DependencyGraph()
    step_a = Step(action="train", provider_hint="model", expected_artifact="model.pkl")
    step_b = Step(action="evaluate", provider_hint="", expected_artifact="metrics.json")
    plan = Plan(
        assumption="model.pkl is available", confidence=0.8, steps=[step_a, step_b]
    )
    graph.add_plan(plan)
    assert graph.get_dependencies("metrics.json") == set()


def test_dependency_graph_detects_cycle_from_inferred_dependencies():
    graph = DependencyGraph()
    step1 = Step(action="use B", provider_hint="", expected_artifact="A")
    step2 = Step(action="use A", provider_hint="", expected_artifact="B")
    plan = Plan(assumption="valid", confidence=0.9, steps=[step1, step2])
    graph.add_plan(plan)
    assert graph.has_cycle()


def test_empty_graph():
    graph = DependencyGraph()
    assert graph.get_dependencies("nonexistent") == set()
    assert graph.get_dependents("nonexistent") == set()
    assert not graph.has_cycle()
