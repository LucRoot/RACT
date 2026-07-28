import json

from ract.dependency_graph import DependencyGraph
from ract.manager import Plan, Step


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


def test_export_json_returns_serializable_string():
    graph = DependencyGraph()
    step1 = Step(action="download", provider_hint="s3", expected_artifact="raw_data")
    step2 = Step(
        action="process raw_data",
        provider_hint="",
        expected_artifact="processed_data",
    )
    plan = Plan(assumption="raw_data exists", confidence=0.9, steps=[step1, step2])
    graph.add_plan(plan)
    text = graph.export_json()
    data = json.loads(text)
    assert data == {"processed_data": ["raw_data"], "raw_data": []}


def test_export_json_writes_to_file(tmp_path):
    graph = DependencyGraph()
    step = Step(action="train", provider_hint="", expected_artifact="model.pkl")
    plan = Plan(assumption="data ready", confidence=0.9, steps=[step])
    graph.add_plan(plan)
    out = tmp_path / "graph.json"
    result = graph.export_json(path=out)
    assert out.read_text(encoding="utf-8") == result
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == {"model.pkl": []}


# RACT 0.1.1 - Trust and tooling
