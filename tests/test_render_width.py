"""B-041c: the session renderer takes the terminal's width (40 to 80 columns).

The checklist and the diff block are drawn by the renderer, so the width it
gets is the width they fit. A narrow terminal gets narrow lines.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract import cli
from ract.repl import ReplSession


class _Console:
    def print(self, *args, **kwargs) -> None:
        pass

    info = success = warning = error = print


def _session(tmp_path: Path) -> ReplSession:
    return ReplSession(
        tmp_path / "ract.yaml",
        dispatch=lambda argv: 0,
        read_line=lambda prompt: "",
        console=_Console(),
        verbs=cli.CLI_VERBS,
    )


@pytest.mark.parametrize(
    "columns, expected",
    [("60", 60), ("30", 40), ("200", 80), ("40", 40)],
)
def test_the_render_width_follows_the_terminal(
    tmp_path, monkeypatch, columns, expected
):
    monkeypatch.setenv("COLUMNS", columns)
    assert _session(tmp_path)._render_width() == expected
