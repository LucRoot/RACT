"""B-105: /undo and /redo say what they did, in different words.

/undo puts a file back to the version before the turn; /redo applies the turn's
change again. Before this card both printed "restored <file>".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tests.test_repl import _session
from tests.test_undo import _turn


@dataclass
class _Result:
    restored: list[str] = field(default_factory=list)

    def lines(self, verb: str) -> list[str]:
        return [f"restored {p}" for p in self.restored]


def test_undo_and_redo_say_different_things(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    _turn(tmp_path, {"a.txt": "two\n"})
    session, _, console = _session(config=tmp_path / "ract.yaml")

    session.handle("/undo")
    undo_text = console.text
    session.handle("/redo")
    redo_text = console.text[len(undo_text) :]

    assert "restored a.txt to the version before the turn" in undo_text
    assert "re-applied a.txt" in redo_text
    assert "restored" not in redo_text
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "two\n"


def test_a_path_with_an_escape_sequence_is_printed_escaped(tmp_path: Path) -> None:
    session, _, console = _session(config=tmp_path / "ract.yaml")

    session._print_reversal(_Result(restored=["evil\x1b[31m.txt"]), "redo")

    assert "\x1b" not in console.text
    assert "re-applied evil" in console.text
