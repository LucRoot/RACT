"""B-061a: ReviewFindings and the finding validator (ADR-0049 D14, D-093)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.review import (
    MAX_CLAIM_CHARS,
    FindingsRefused,
    parse_findings,
    validate,
)

CALC = "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "calc.py").write_bytes(CALC.encode("utf-8"))
    return tmp_path


def _finding(**over: object) -> dict:
    base = {
        "path": "src/calc.py",
        "line": 2,
        "severity": "defect",
        "claim": "add subtracts",
        "evidence": "return a - b",
    }
    return {**base, **over}


def _run(repo: Path, *entries: dict, changed=None):
    review = parse_findings({"findings": list(entries)})
    return validate(repo, review, changed or {"src/calc.py": {2}})


def test_a_good_finding_is_kept(repo: Path) -> None:
    result = _run(repo, _finding())
    assert [(f.path, f.line, f.severity) for f in result.kept] == [
        ("src/calc.py", 2, "defect")
    ]
    assert result.dropped_total == 0


def test_a_finding_without_a_path_and_line_is_dropped(repo: Path) -> None:
    entry = _finding()
    del entry["path"], entry["line"]
    result = _run(repo, entry, _finding())
    assert len(result.kept) == 1 and result.dropped_total == 1


def test_a_finding_whose_evidence_is_not_at_the_line_is_dropped(repo: Path) -> None:
    result = _run(repo, _finding(evidence="return a * b"), _finding(line=99))
    assert result.kept == []
    assert result.dropped == {"evidence not at that line": 1, "no such line": 1}


def test_evidence_two_lines_away_still_counts(repo: Path) -> None:
    result = _run(repo, _finding(line=4, severity="note", evidence="return a - b"))
    assert len(result.kept) == 1


def test_a_defect_on_an_unchanged_line_becomes_a_note(repo: Path) -> None:
    result = _run(repo, _finding(line=6), changed={"src/calc.py": {2}})
    assert [f.severity for f in result.kept] == ["note"]
    assert result.downgraded == 1


def test_an_approval_in_the_review_reply_changes_nothing(repo: Path) -> None:
    with pytest.raises(FindingsRefused):
        parse_findings({"findings": [], "approve": True, "verdict": "done"})
    result = _run(repo, _finding(approve=True), _finding())
    assert len(result.kept) == 1 and result.dropped_total == 1
    assert not hasattr(result, "verdict")


def test_a_path_outside_the_project_is_dropped(repo: Path) -> None:
    result = _run(
        repo,
        _finding(path="../outside.py"),
        _finding(path=".git/config", line=1),
        _finding(path="C:/Windows/win.ini", line=1),
    )
    assert result.kept == []
    assert result.dropped == {"a path outside the project or protected": 3}


def test_a_claim_over_300_characters_is_cut_and_counted(repo: Path) -> None:
    result = _run(repo, _finding(claim="x " * 400))
    assert len(result.kept[0].claim) == MAX_CLAIM_CHARS
    assert result.claims_cut == 1


def test_crlf_in_the_file_does_not_break_the_evidence_match(repo: Path) -> None:
    (repo / "src" / "calc.py").write_bytes(CALC.replace("\n", "\r\n").encode())
    result = _run(repo, _finding(evidence="def add(a, b):\r\n    return a - b"))
    assert len(result.kept) == 1


def test_every_kept_field_is_printable(repo: Path) -> None:
    (repo / "src" / "calc.py").write_bytes(
        CALC.replace("return a - b", "return a - b  # \x1b[2J").encode(),
    )
    result = _run(
        repo,
        _finding(
            claim="bad \x1b]0;title\x07 \u202e", evidence="return a - b  # \x1b[2J"
        ),
    )
    kept = result.kept[0]
    for text in (kept.path, kept.claim, kept.evidence):
        assert "\x1b" not in text and "\x07" not in text and "\u202e" not in text


def test_more_than_twenty_findings_are_cut_and_counted(repo: Path) -> None:
    result = _run(repo, *[_finding() for _ in range(25)])
    assert len(result.kept) == 20
    assert result.dropped["over the limit of 20"] == 5


@pytest.mark.parametrize(
    "reply", [None, [], {"findings": "x"}, {"findings": [], "other": 1}]
)
def test_a_reply_that_is_not_findings_is_refused(reply: object) -> None:
    with pytest.raises(FindingsRefused):
        parse_findings(reply)
