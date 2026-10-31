"""B-148: the work at run entry is bounded; past a bound it says what it skipped and goes on.

Small fixtures with lowered caps stand in for a 50,000-file repository (the
measurement on a generated one is in the BUILDER log).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ract import turn_context
from ract.policy import allowlist


def _repo(tmp_path: Path, tests: int = 5, size: int = 10) -> Path:
    root = tmp_path / "ws"
    (root / "tests").mkdir(parents=True)
    for n in range(tests):
        (root / "tests" / f"test_{n}.py").write_text("x" * size, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


@pytest.fixture
def notices():  # type: ignore[no-untyped-def]
    seen: list[dict] = []
    turn_context.bind(
        None, lambda kind, data: seen.append(data) if kind == "notice" else None
    )
    try:
        yield seen
    finally:
        turn_context.bind(None)


def test_within_the_bounds_every_entry_point_is_read(tmp_path: Path, notices) -> None:
    digests = allowlist.entry_point_digests(_repo(tmp_path))
    assert digests is not None and len(digests) == 5
    assert notices == []


@pytest.mark.parametrize(
    ("bound", "value", "said"),
    [
        ("MAX_ENTRY_POINTS", 3, "more than 3 entry points"),
        ("MAX_ENTRY_BYTES", 25, "MiB of them"),
        ("ENTRY_DEADLINE_S", -1.0, "took over"),
    ],
)
def test_past_a_bound_the_record_is_unknown_and_the_turn_says_so(
    tmp_path: Path, monkeypatch, notices, bound: str, value, said: str
) -> None:
    monkeypatch.setattr(allowlist, bound, value)
    assert allowlist.entry_point_digests(_repo(tmp_path)) is None
    assert notices and said in notices[0]["text"]
    assert "every tier-3 command asks" in notices[0]["text"]


def test_an_unknown_record_makes_a_command_ask(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(allowlist, "MAX_ENTRY_POINTS", 1)
    changes = allowlist.changed_entry_points(_repo(tmp_path), "0" * 64, set())
    assert [(c.path, c.reason) for c in changes] == [(".", allowlist.UNKNOWN)]


def test_the_signing_snapshot_stops_at_its_deadline_and_says_so(
    tmp_path: Path, monkeypatch, notices
) -> None:
    from ract import provenance_wiring

    root = _repo(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    monkeypatch.setattr(provenance_wiring, "_DEADLINE_S", -1.0)
    assert provenance_wiring._tracked_text(root) == {}
    assert notices and "took over" in notices[0]["text"]
