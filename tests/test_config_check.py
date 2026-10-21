"""Tests for shared ract.yaml interpretation (manager resolution, misplaced keys)."""

from __future__ import annotations

from pathlib import Path

from ract.cli import main
from ract.config_check import find_config_problems, resolve_manager_provider
from ract.doctor import RactDoctor
from ract.harness import Harness

LOCAL = {"adapter": "local_http", "url": "http://127.0.0.1:8080/v1", "model": "m"}


# --- resolve_manager_provider -------------------------------------------------


def test_explicit_manager_provider_wins():
    config = {"manager_provider": "bolt", "providers": {"bolt": LOCAL, "north": LOCAL}}
    assert resolve_manager_provider(config) == ("bolt", None)


def test_explicit_manager_provider_must_be_defined():
    config = {"manager_provider": "ghost", "providers": {"bolt": LOCAL}}
    name, error = resolve_manager_provider(config)
    assert name is None
    assert "ghost" in error and "bolt" in error


def test_legacy_local_default_still_resolves():
    config = {"providers": {"local": LOCAL, "north": LOCAL}}
    assert resolve_manager_provider(config) == ("local", None)


def test_single_provider_is_used_without_manager_provider():
    config = {"providers": {"bolt": LOCAL}}
    assert resolve_manager_provider(config) == ("bolt", None)


def test_ambiguous_providers_error_names_the_real_problem():
    """Regression: this used to surface as "Provider slot 'local' is not configured"."""
    config = {"providers": {"bolt": LOCAL, "north": LOCAL}}
    name, error = resolve_manager_provider(config)
    assert name is None
    assert "manager_provider" in error
    assert "'local'" not in error
    assert "bolt" in error and "north" in error


def test_nested_keys_are_called_out_in_the_error():
    config = {
        "project": {
            "name": "x",
            "manager_provider": "bolt",
            "providers": {"bolt": LOCAL, "north": LOCAL},
        }
    }
    name, error = resolve_manager_provider(config)
    assert name is None
    assert "indented under 'project:'" in error


# --- find_config_problems -----------------------------------------------------


def test_clean_config_has_no_problems():
    config = {
        "project": {"name": "x"},
        "manager_provider": "bolt",
        "providers": {"bolt": LOCAL},
    }
    assert find_config_problems(config) == []


def test_keys_nested_under_project_are_reported():
    config = {"project": {"name": "x", "manager_provider": "bolt", "providers": {}}}
    problems = find_config_problems(config)
    assert any("'manager_provider'" in p and "top level" in p for p in problems)
    assert any("'providers'" in p and "top level" in p for p in problems)


def test_prompt_file_key_is_reported_as_unread():
    problems = find_config_problems({"prompt_file": "/tmp/manager.txt"})
    assert any("prompt_file" in p and "manager.txt" in p for p in problems)


def test_prompt_file_message_follows_prompts_dir():
    problems = find_config_problems({"prompt_file": "x", "prompts_dir": "p"})
    assert any("'p/manager.txt'" in p for p in problems)


def test_type_instead_of_adapter_is_reported():
    config = {"providers": {"bolt": {"type": "local_http", "base_url": "http://x"}}}
    assert any("use 'adapter:'" in p for p in find_config_problems(config))


def test_alternate_max_token_spellings_are_reported():
    config = {"providers": {"bolt": {**LOCAL, "max_output_tokens": 100}}}
    assert any("use 'max_tokens:'" in p for p in find_config_problems(config))


def test_non_mapping_config_does_not_raise():
    assert find_config_problems([]) == []  # type: ignore[arg-type]


# --- doctor -------------------------------------------------------------------


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "ract.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_doctor_reports_nested_keys(tmp_path):
    path = _write(
        tmp_path,
        "project:\n  name: demo\n  manager_provider: bolt\n"
        "providers:\n  bolt:\n    adapter: local_http\n  north:\n    adapter: local_http\n",
    )
    results = {r.name: r for r in RactDoctor(path).diagnose()}
    assert not results["manager_provider"].passed
    assert "indented under 'project:'" in results["manager_provider"].message
    assert not results["config_layout"].passed


def test_doctor_clean_config_has_no_layout_check(tmp_path):
    path = _write(
        tmp_path,
        "project:\n  name: demo\nmanager_provider: bolt\n"
        "providers:\n  bolt:\n    adapter: local_http\n",
    )
    names = [r.name for r in RactDoctor(path).diagnose()]
    assert "config_layout" not in names
    assert all(r.passed for r in RactDoctor(path).diagnose())


# --- harness ------------------------------------------------------------------


def test_harness_error_for_unresolvable_manager_is_actionable(tmp_path):
    path = _write(
        tmp_path,
        "project:\n  name: demo\nproviders:\n  bolt:\n    adapter: local_http\n"
        "  north:\n    adapter: local_http\n",
    )
    result = Harness.from_config_path(path)
    assert not result.is_ok()
    assert "manager_provider is not set" in result.error
    assert "Provider slot 'local'" not in result.error


# --- ract config validate -----------------------------------------------------


def test_config_validate_fails_when_manager_cannot_resolve(tmp_path, capsys):
    path = _write(
        tmp_path,
        "project:\n  name: demo\nproviders:\n  a:\n    adapter: local_http\n"
        "  b:\n    adapter: local_http\n",
    )
    assert main(["config", "validate", "--config", str(path)]) == 1
    assert "manager_provider" in capsys.readouterr().err


def test_config_validate_warns_about_unread_keys(tmp_path, capsys):
    path = _write(
        tmp_path,
        "project:\n  name: demo\nmanager_provider: a\nprompt_file: x.txt\n"
        "providers:\n  a:\n    adapter: local_http\n",
    )
    assert main(["config", "validate", "--config", str(path)]) == 0
    captured = capsys.readouterr()
    assert "warning" in captured.err and "prompt_file" in captured.err
    assert "config is valid" in captured.out
