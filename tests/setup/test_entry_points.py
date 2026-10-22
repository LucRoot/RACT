"""B-015: every way a user meets a missing ract.yaml points to setup."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ract import cli
from ract.setup import wizard
from tests.test_headless import _ract


def test_bare_ract_offers_setup_and_n_opens_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    ran: list[Any] = []
    monkeypatch.setattr(wizard, "run", lambda *a, **k: ran.append(a) or 0)

    assert cli._offer_setup(ask=lambda prompt: "n") is True
    assert ran == []
    assert "No ract.yaml in this directory" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("code", "opens"),
    [
        (wizard.EXIT_OK, True),
        (wizard.EXIT_PROVIDER, True),
        (wizard.EXIT_INTERRUPTED, False),
    ],
)
def test_yes_runs_setup_then_opens_the_session_when_it_finished(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: int, opens: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(wizard, "run", lambda *a, **k: code)

    assert cli._offer_setup(ask=lambda prompt: "") is opens


def test_end_of_input_at_the_offer_opens_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    def eof(prompt: str) -> str:
        raise EOFError

    assert cli._offer_setup(ask=eof) is False


def test_bare_ract_without_a_terminal_points_to_the_answers_file(
    tmp_path: Path,
) -> None:
    result = _ract(tmp_path)

    assert result.returncode == 2  # the intent is still required
    assert "ract setup --answers FILE" in result.stderr


def test_ract_run_without_a_config_points_to_setup(tmp_path: Path) -> None:
    result = _ract(tmp_path, "run", "--config", "ract.yaml", "--", "fix it")

    assert result.returncode != 0
    assert "hint: run `ract setup` here" in result.stdout + result.stderr


def test_headless_without_a_config_points_to_setup(tmp_path: Path) -> None:
    result = _ract(tmp_path, "-p", "fix it")

    assert result.returncode == 2
    assert "ract setup --answers FILE" in result.stderr


def test_the_session_hint_for_a_missing_config_names_setup() -> None:
    from ract.session_turn import hint_for

    assert hint_for("Configuration file not found: ract.yaml") == (
        "run `ract setup` here to create one"
    )
