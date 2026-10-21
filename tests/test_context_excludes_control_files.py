"""RACT's own control files must not be injected into step context."""

from __future__ import annotations

from ract.harness import _curate_context

MANAGER_TEXT = "You are a planning manager. Respond with ONLY a single JSON object."


def _make_workspace(root):
    (root / "hello.py").write_text(
        "def greet(name):\n    return name\n", encoding="utf-8"
    )
    (root / "manager.txt").write_text(MANAGER_TEXT, encoding="utf-8")
    (root / "ract.yaml").write_text("manager_provider: bolt\n", encoding="utf-8")
    (root / ".ract").mkdir()
    (root / ".ract" / "state.json").write_text('{"k": 1}', encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "manager.txt").write_text(MANAGER_TEXT, encoding="utf-8")


def test_project_source_is_included(tmp_path):
    _make_workspace(tmp_path)
    context = _curate_context(tmp_path, "add a docstring", 4096)
    assert "def greet(name)" in context


def test_manager_prompt_is_not_included(tmp_path):
    """Regression: a root-level manager.txt made every step return a JSON plan."""
    _make_workspace(tmp_path)
    context = _curate_context(tmp_path, "add a docstring", 4096)
    assert "planning manager" not in context
    assert "--- manager.txt" not in context
    assert "--- sub/manager.txt" not in context


def test_config_and_state_are_not_included(tmp_path):
    _make_workspace(tmp_path)
    context = _curate_context(tmp_path, "add a docstring", 4096)
    assert "ract.yaml" not in context
    assert ".ract/state.json" not in context


def test_custom_prompts_dir_is_excluded(tmp_path):
    (tmp_path / "hello.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "my_prompts").mkdir()
    (tmp_path / "my_prompts" / "other.md").write_text("PROMPT BODY", encoding="utf-8")
    context = _curate_context(tmp_path, "intent", 4096, prompts_dir="my_prompts")
    assert "PROMPT BODY" not in context
    assert "x = 1" in context


def test_workspace_with_only_control_files_yields_empty_context(tmp_path):
    (tmp_path / "manager.txt").write_text(MANAGER_TEXT, encoding="utf-8")
    (tmp_path / "ract.yaml").write_text("manager_provider: a\n", encoding="utf-8")
    assert _curate_context(tmp_path, "intent", 4096) == ""
