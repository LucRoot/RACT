# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the Legacy Whisperer subagent."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path
from unittest.mock import patch

from rootact.cli import main
from rootact.legacy_whisperer import LegacyWhisperer
from rootact.providers.base import ProviderAdapter
from rootact.rooted import Rooted


class FakeProvider(ProviderAdapter):
    """Minimal fake provider that echoes the prompt."""

    def __init__(self, response: str = "brief text") -> None:
        super().__init__({})
        self._response = response

    @property
    def name(self) -> str:
        return "fake"

    def models(self) -> list[str]:
        return ["fake"]

    def capabilities(self) -> set[str]:
        return {"chat"}

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> Rooted[dict]:
        return Rooted(
            value={"choices": [{"message": {"content": self._response}}]},
            assumption="fake provider responds",
            confidence=1.0,
            provenance=["fake_provider.complete"],
        )


def _seed_project(project_dir: Path) -> None:
    (project_dir / "widget.py").write_text(
        "from typing import Optional\n\n"
        "class Widget:\n"
        '    DEFAULT_NAME = "thing"\n'
        "    def __init__(self, name: Optional[str] = None) -> None:\n"
        "        self.name = name or self.DEFAULT_NAME\n",
        encoding="utf-8",
    )
    (project_dir / "utils.py").write_text(
        "import os\n\n"
        "def helper(path: str) -> str:\n"
        "    return os.path.basename(path)\n",
        encoding="utf-8",
    )


def test_brief_returns_provider_response(tmp_path: Path):
    _seed_project(tmp_path)
    whisperer = LegacyWhisperer(tmp_path, FakeProvider("Use Widget for state."))
    result = whisperer.brief("add state management")

    assert result.is_ok()
    assert result.unwrap() == "Use Widget for state."
    assert result.provenance[-1].startswith("provider:")


def test_brief_includes_style_stats_in_prompt(tmp_path: Path):
    _seed_project(tmp_path)
    captured: list[str] = []

    class CapturingProvider(FakeProvider):
        def complete(self, messages, **kwargs):
            captured.append(messages[0]["content"])
            return super().complete(messages, **kwargs)

    whisperer = LegacyWhisperer(tmp_path, CapturingProvider("brief"))
    whisperer.brief("add state management")

    assert captured
    prompt = captured[0]
    assert "Style fingerprint:" in prompt
    assert "files=" in prompt
    assert "functions=" in prompt
    assert "Candidate files:" in prompt


def test_brief_uses_provided_paths(tmp_path: Path):
    _seed_project(tmp_path)
    captured: list[str] = []

    class CapturingProvider(FakeProvider):
        def complete(self, messages, **kwargs):
            captured.append(messages[0]["content"])
            return super().complete(messages, **kwargs)

    whisperer = LegacyWhisperer(tmp_path, CapturingProvider("brief"))
    whisperer.brief("add state management", paths=["utils.py"])

    prompt = captured[0]
    # Candidate files section should contain only the requested path.
    candidate_section = prompt.split("Candidate files:")[1].split(
        "Most-referenced files:"
    )[0]
    assert "utils.py" in candidate_section
    assert "widget.py" not in candidate_section


def test_brief_degrades_without_git(tmp_path: Path):
    _seed_project(tmp_path)
    whisperer = LegacyWhisperer(tmp_path, FakeProvider("No git, still works."))
    result = whisperer.brief("add state management")

    assert result.is_ok()
    assert result.unwrap() == "No git, still works."


def test_cli_whisper(capsys, tmp_path: Path):
    config = tmp_path / "rootact.yaml"
    config.write_text(
        "project:\n  name: test\nmanager_provider: fake\nproviders:\n  fake:\n"
        "    adapter: local_http\n    url: http://127.0.0.1:1/v1\n    model: fake\n",
        encoding="utf-8",
    )

    def _fake_brief(intent, paths=None):
        return Rooted(
            value=f"Brief for: {intent}",
            assumption="fake",
            confidence=1.0,
            provenance=["fake"],
        )

    with patch("rootact.cli.LegacyWhisperer") as MockWhisperer:
        instance = MockWhisperer.return_value
        instance.brief = _fake_brief
        code = main(["whisper", "--intent", "add logging", "--config", str(config)])
        out = capsys.readouterr().out

    assert code == 0
    assert "Brief for: add logging" in out
    assert "Root Knot dialect note" in out


def test_brief_returns_error_when_no_candidates(tmp_path: Path):
    whisperer = LegacyWhisperer(tmp_path, FakeProvider("brief"))
    result = whisperer.brief("work on nothing")
    assert not result.is_ok()
    assert "No candidate files" in (result.error or "")


def test_brief_returns_error_on_provider_failure(tmp_path: Path):
    _seed_project(tmp_path)

    class FailingProvider(FakeProvider):
        def complete(self, messages, **kwargs):
            return Rooted(
                value=None,
                error="provider down",
                assumption="ok",
                confidence=0.0,
            )

    whisperer = LegacyWhisperer(tmp_path, FailingProvider())
    result = whisperer.brief("add state management")
    assert not result.is_ok()
    assert "provider down" in (result.error or "")


def test_brief_returns_error_on_empty_response(tmp_path: Path):
    _seed_project(tmp_path)
    whisperer = LegacyWhisperer(tmp_path, FakeProvider(""))
    result = whisperer.brief("add state management")
    assert not result.is_ok()
    assert "empty response" in (result.error or "")


def test_brief_catches_provider_exception(tmp_path: Path):
    _seed_project(tmp_path)

    class ExplodingProvider(FakeProvider):
        def complete(self, messages, **kwargs):
            raise RuntimeError("boom")

    whisperer = LegacyWhisperer(tmp_path, ExplodingProvider())
    result = whisperer.brief("add state management")
    assert not result.is_ok()
    assert "boom" in (result.error or "")


def test_candidate_paths_falls_back_to_keyword_search(tmp_path: Path):
    _seed_project(tmp_path)
    whisperer = LegacyWhisperer(tmp_path, FakeProvider("brief"))
    paths = whisperer._candidate_paths("widget", None)
    assert any("widget.py" in str(p) for p in paths)
