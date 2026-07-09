# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for Chesterton's Fence subagent."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path
from unittest.mock import patch

from rootact.chestertons_fence import ChestertonsFence
from rootact.cli import main
from rootact.providers.base import ProviderAdapter
from rootact.rooted import Rooted


class FakeProvider(ProviderAdapter):
    """Fake provider that returns a canned response."""

    def __init__(self, response: str = "Handles shutdown race condition.") -> None:
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


def test_inspect_returns_provider_response(tmp_path: Path):
    target = tmp_path / "legacy.py"
    target.write_text("def old_way():\n    pass\n", encoding="utf-8")
    fence = ChestertonsFence(tmp_path, FakeProvider("Reason here"))

    with patch.object(fence, "_run_git", return_value="abc123 fix race\n"):
        result = fence.inspect(target)

    assert result.is_ok()
    assert result.unwrap() == "Reason here"
    assert result.confidence == 0.8


def test_inspect_relative_path_does_not_crash(tmp_path: Path):
    target = tmp_path / "src" / "rootact" / "rooted.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def rooted():\n    pass\n", encoding="utf-8")
    fence = ChestertonsFence(tmp_path, FakeProvider("Works with relative path."))

    with patch.object(fence, "_run_git", return_value="abc123 init\n"):
        result = fence.inspect("src/rootact/rooted.py")

    assert result.error is None
    assert result.value == "Works with relative path."


def test_inspect_low_confidence_when_no_reason(tmp_path: Path):
    target = tmp_path / "legacy.py"
    target.write_text("def old_way():\n    pass\n", encoding="utf-8")
    fence = ChestertonsFence(tmp_path, FakeProvider("No plausible reason found."))

    with patch.object(fence, "_run_git", return_value="abc123 fix race\n"):
        result = fence.inspect(target)

    assert result.value == "No plausible reason found."
    assert result.confidence == 0.3
    assert not result.is_ok()
    assert "No plausible reason found" in (result.error or "")


def test_inspect_fails_for_missing_file(tmp_path: Path):
    fence = ChestertonsFence(tmp_path, FakeProvider())
    result = fence.inspect(tmp_path / "missing.py")

    assert not result.is_ok()
    assert "File not found" in (result.error or "")


def test_cli_fence_inspect(capsys, tmp_path: Path):
    config = tmp_path / "rootact.yaml"
    config.write_text(
        "project:\n  name: test\nmanager_provider: fake\nproviders:\n  fake:\n"
        "    adapter: local_http\n    url: http://127.0.0.1:1/v1\n    model: fake\n",
        encoding="utf-8",
    )
    target = tmp_path / "legacy.py"
    target.write_text("pass\n", encoding="utf-8")

    def _fake_inspect(path, lines=None):
        return Rooted(
            value="Race-condition guard.",
            assumption="fake",
            confidence=0.8,
            provenance=["fake"],
        )

    with patch("rootact.cli.ChestertonsFence") as MockFence:
        instance = MockFence.return_value
        instance.inspect = _fake_inspect
        code = main(
            [
                "fence",
                "inspect",
                "--file",
                str(target),
                "--lines",
                "1-1",
                "--config",
                str(config),
            ]
        )
        out = capsys.readouterr().out

    assert code == 0
    assert "Race-condition guard." in out
    assert "guard, not a veto" in out


# RACT 0.1.1 - Trust and Tooling
