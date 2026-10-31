"""Tests for the ract plan CLI commands."""

from __future__ import annotations


from ract.cli import main
from ract.manager import Plan, Step
from ract.plan_serializers import save_plan
from ract.session_store import SessionStore


def test_plan_export_writes_session_plan(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "ract.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")

    store = SessionStore(tmp_path / ".ract" / "sessions")
    plan = Plan(
        assumption="test assumption",
        confidence=0.9,
        steps=[Step("write code", "chat", "src/x.py")],
    )
    store.save(
        "demo", {"intent": "test", "plan": plan, "artifacts": {}, "outcomes": []}
    )

    output = tmp_path / "plan.json"
    code = main(
        [
            "plan",
            "export",
            "--session",
            "demo",
            "--output",
            str(output),
            "--config",
            str(config_path),
        ]
    )
    assert code == 0
    assert output.is_file()
    text = output.read_text(encoding="utf-8")
    assert "test assumption" in text
    assert "write code" in text


def test_plan_export_missing_session_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "ract.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    output = tmp_path / "plan.json"
    code = main(
        [
            "plan",
            "export",
            "--session",
            "missing",
            "--output",
            str(output),
            "--config",
            str(config_path),
        ]
    )
    assert code == 1
    assert "not found" in capsys.readouterr().err.lower()


def test_plan_replay_dry_run(tmp_path, capsys):
    plan = Plan(
        assumption="a",
        confidence=1.0,
        steps=[Step("step one", "chat", "a.py"), Step("step two", "chat", "b.py")],
    )
    plan_path = tmp_path / "plan.json"
    save_plan(plan, plan_path)

    code = main(["plan", "replay", "--plan", str(plan_path), "--dry-run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "2/2 steps passed" in out
    assert "step one" in out
    assert "step two" in out


# RACT 0.1.1 - Trust and tooling


def test_a_saved_plan_with_planned_reads_back_as_a_plan(tmp_path) -> None:
    """B-137 added Plan.planned; a saved session's plan must still decode."""
    from ract.manager import Plan as P
    from ract.manager import Step as S

    store = SessionStore(tmp_path / "sessions")
    plan = P("a", 0.5, [S("fix", "", "", agent=True)], planned=False)
    store.save("s", {"intent": "x", "plan": plan, "artifacts": {}, "outcomes": []})
    back = store.load("s")["plan"]
    assert isinstance(back, P) and back.planned is False and back.steps[0].agent


def test_an_agent_plan_survives_export_and_replay() -> None:
    from ract.manager import Plan as P
    from ract.manager import Step as S
    from ract.plan_serializers import plan_from_dict, plan_to_dict

    back = plan_from_dict(
        plan_to_dict(P("a", 1.0, [S("fix", "", "", agent=True)], planned=False))
    )
    assert back.planned is False and back.steps[0].agent is True
    old = plan_from_dict({"assumption": "a", "confidence": 1.0, "steps": []})
    assert old.planned is True  # a plan written before B-137 reads as planned
