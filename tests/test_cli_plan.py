# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the rootact plan CLI commands."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.cli import main
from rootact.manager import Plan, Step
from rootact.plan_serializers import save_plan
from rootact.session_store import SessionStore


def test_plan_export_writes_session_plan(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")

    store = SessionStore(tmp_path / ".rootact" / "sessions")
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
    config_path = tmp_path / "rootact.yaml"
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


# RACT 0.1.1 - Trust and Tooling
