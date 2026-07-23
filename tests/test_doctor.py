# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for RACT doctor diagnostics."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from unittest.mock import MagicMock, patch

from ract.doctor import RactDoctor
from ract.rooted import Rooted


SAMPLE_CONFIG = """\
project:
  name: demo

manager_provider: local

providers:
  local:
    adapter: local_http
    url: http://127.0.0.1:11434/v1
    model: nemotron

prompts_dir: prompts
"""


def test_doctor_passes_valid_config(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(SAMPLE_CONFIG, encoding="utf-8")
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "manager.txt").write_text("manager prompt", encoding="utf-8")

    results = RactDoctor(config).diagnose()
    assert all(r.passed for r in results)


def test_doctor_fails_missing_config(tmp_path):
    config = tmp_path / "ract.yaml"
    results = RactDoctor(config).diagnose()
    assert results[0].name == "config_exists"
    assert not results[0].passed


def test_doctor_fails_missing_project_name(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(
        "manager_provider: local\nproviders:\n  local:\n    adapter: local_http\n",
        encoding="utf-8",
    )
    results = RactDoctor(config).diagnose()
    project_check = next(r for r in results if r.name == "project_name")
    assert not project_check.passed


def test_doctor_fails_missing_provider_adapter(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(
        "project:\n  name: demo\nmanager_provider: local\nproviders:\n  local:\n    url: http://x\n",
        encoding="utf-8",
    )
    results = RactDoctor(config).diagnose()
    providers_check = next(r for r in results if r.name == "providers")
    assert not providers_check.passed


def test_doctor_detects_missing_env_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = tmp_path / "ract.yaml"
    config.write_text(
        "project:\n  name: demo\nmanager_provider: openai\nproviders:\n  openai:\n"
        "    adapter: openai\n    url: https://api.openai.com/v1\n"
        "    api_key: ${OPENAI_API_KEY}\n",
        encoding="utf-8",
    )
    results = RactDoctor(config).diagnose()
    providers_check = next(r for r in results if r.name == "providers")
    assert not providers_check.passed
    assert "OPENAI_API_KEY" in providers_check.message


def test_doctor_check_providers_reachable(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(SAMPLE_CONFIG, encoding="utf-8")
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "manager.txt").write_text("manager prompt", encoding="utf-8")

    mock_router = MagicMock()
    mock_router.health_check.return_value = Rooted(
        value=True,
        assumption="reachable",
        confidence=1.0,
        provenance=["test"],
    )

    with patch("ract.doctor.ProviderRouter", return_value=mock_router):
        results = RactDoctor(config).diagnose(check_providers=True)

    reachability = [r for r in results if r.name.startswith("provider_reachable:")]
    assert len(reachability) == 1
    assert reachability[0].passed
    assert "reachable" in reachability[0].message


def test_doctor_check_providers_unreachable(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(SAMPLE_CONFIG, encoding="utf-8")
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "manager.txt").write_text("manager prompt", encoding="utf-8")

    mock_router = MagicMock()
    mock_router.health_check.return_value = Rooted(
        value=False,
        assumption="reachable",
        confidence=0.0,
        provenance=["test"],
        error="connection refused",
    )

    with patch("ract.doctor.ProviderRouter", return_value=mock_router):
        results = RactDoctor(config).diagnose(check_providers=True)

    reachability = [r for r in results if r.name.startswith("provider_reachable:")]
    assert len(reachability) == 1
    assert not reachability[0].passed
    assert "connection refused" in reachability[0].message


def test_doctor_check_providers_skipped_by_default(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(SAMPLE_CONFIG, encoding="utf-8")
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "manager.txt").write_text("manager prompt", encoding="utf-8")

    with patch("ract.doctor.ProviderRouter") as mock_cls:
        results = RactDoctor(config).diagnose()

    mock_cls.assert_not_called()
    reachability = [r for r in results if r.name.startswith("provider_reachable:")]
    assert not reachability


def test_doctor_fails_invalid_yaml(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("project: name: demo", encoding="utf-8")
    results = RactDoctor(config).diagnose()
    parse_check = next(r for r in results if r.name == "config_parse")
    assert not parse_check.passed


def test_doctor_fails_non_mapping_yaml(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("- just\n- a\n- list\n", encoding="utf-8")
    results = RactDoctor(config).diagnose()
    parse_check = next(r for r in results if r.name == "config_parse")
    assert not parse_check.passed


def test_doctor_fails_missing_manager_provider(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(
        "project:\n  name: demo\nproviders:\n  local:\n    adapter: local_http\n",
        encoding="utf-8",
    )
    results = RactDoctor(config).diagnose()
    check = next(r for r in results if r.name == "manager_provider")
    assert not check.passed


def test_doctor_fails_manager_provider_not_in_providers(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(
        "project:\n  name: demo\nmanager_provider: missing\nproviders:\n  local:\n    adapter: local_http\n",
        encoding="utf-8",
    )
    results = RactDoctor(config).diagnose()
    check = next(r for r in results if r.name == "manager_provider")
    assert not check.passed


def test_doctor_fails_no_providers(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(
        "project:\n  name: demo\nmanager_provider: local\n", encoding="utf-8"
    )
    results = RactDoctor(config).diagnose()
    check = next(r for r in results if r.name == "providers")
    assert not check.passed


def test_doctor_fails_provider_not_mapping(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(
        "project:\n  name: demo\nmanager_provider: local\nproviders:\n  local: not-a-mapping\n",
        encoding="utf-8",
    )
    results = RactDoctor(config).diagnose()
    check = next(r for r in results if r.name == "providers")
    assert not check.passed


def test_doctor_reachability_skips_invalid_provider_settings(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(
        "project:\n  name: demo\nmanager_provider: local\nproviders:\n  local: not-a-mapping\n",
        encoding="utf-8",
    )
    results = RactDoctor(config).diagnose(check_providers=True)
    assert not any(r.name.startswith("provider_reachable:") for r in results)


def test_doctor_prompt_file_falls_back_to_default(tmp_path, monkeypatch):
    config = tmp_path / "ract.yaml"
    config.write_text(SAMPLE_CONFIG, encoding="utf-8")
    default_prompt = tmp_path / "default_manager.txt"
    default_prompt.write_text("default", encoding="utf-8")

    with patch("ract.doctor._default_manager_prompt_path", return_value=default_prompt):
        results = RactDoctor(config).diagnose()

    check = next(r for r in results if r.name == "prompt_file")
    assert check.passed
    assert "bundled default" in check.message


def test_doctor_prompt_file_missing_and_no_default(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(SAMPLE_CONFIG, encoding="utf-8")

    with patch(
        "ract.doctor._default_manager_prompt_path",
        return_value=tmp_path / "nope.txt",
    ):
        results = RactDoctor(config).diagnose()

    check = next(r for r in results if r.name == "prompt_file")
    assert not check.passed


def test_doctor_skill_missing(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(
        SAMPLE_CONFIG + "\nskill: missing_skill\n",
        encoding="utf-8",
    )
    results = RactDoctor(config).diagnose()
    check = next(r for r in results if r.name == "skills")
    assert not check.passed
    assert "missing_skill" in check.message


# RACT 0.1.1 - Trust and tooling
