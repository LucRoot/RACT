"""B-037a: extract and verify the file and line citations in an answer.

The model's text is hostile input. Protected and outside paths are never
opened: the file-read function is spied on, and the test fails if it is called
on one of them.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from ract import citations
from ract.citations import MAX_CHECKED, extract, verify


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "app" / "config.py").write_text(
        "import os\n\n\ndef load_config(path):\n    return path\n\n\nX = 1\nY = 2\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "app" / "main.py").write_text(
        "from app.config import load_config\nCONFIG = load_config('x')\n",
        encoding="utf-8",
    )
    (tmp_path / "ten.py").write_text(
        "".join(f"line {i}\n" for i in range(1, 11)), encoding="utf-8"
    )
    return tmp_path


def _paths(text: str) -> list[tuple[str, int, int, str | None]]:
    return [(c.path, c.start, c.end, c.symbol) for c in extract(text)]


# ---------------------------------------------------------------- 1. extraction


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("see src/app/config.py:12", [("src/app/config.py", 12, 12, None)]),
        ("see src/app/config.py:12-18.", [("src/app/config.py", 12, 18, None)]),
        ("see src/app/config.py:12,14", [("src/app/config.py", 12, 14, None)]),
        ("at `x.py` line 4", [("x.py", 4, 4, None)]),
        ("at `x.py` line 4-6", [("x.py", 4, 6, None)]),
        (
            "the loader is `load_config` in src/app/config.py:4",
            [("src/app/config.py", 4, 4, "load_config")],
        ),
        ("(see a.py:3), then b.py:9;", [("a.py", 3, 3, None), ("b.py", 9, 9, None)]),
        ("visit https://example.com:8080/x", []),
        ("see example.com:8080/x", []),
        ("Python 3.11:2 is the version", []),
        ("at 10:30 we met", []),
        ("C:\\Windows\\x.py:1 is not ours", [("C:\\Windows\\x.py", 1, 1, None)]),
        ("the file x.py without a line", []),
        ("a path ../up.py:1 is not relative", [("../up.py", 1, 1, None)]),
        ("and README.md:1 too", [("README.md", 1, 1, None)]),
        ("nested pkg/sub/mod.py:7-7", [("pkg/sub/mod.py", 7, 7, None)]),
        ("two: a.py:1 and a.py:1", [("a.py", 1, 1, None), ("a.py", 1, 1, None)]),
        ("empty `` line 3", []),
        ("end of line.py:99!", [("line.py", 99, 99, None)]),
        ("a.b.c:5 has a dotted name", [("a.b.c", 5, 5, None)]),
    ],
)
def test_extraction_table(
    text: str, expected: list[tuple[str, int, int, str | None]]
) -> None:
    assert _paths(text) == expected


def test_order_is_the_order_of_appearance() -> None:
    text = "later b.py:2 then earlier-looking a.py:1"
    assert [c.path for c in extract(text)] == ["b.py", "a.py"]


# ---------------------------------------------------------------- 2. verified


def test_a_line_range_inside_the_file_is_verified(repo: Path) -> None:
    results = verify(repo, extract("ten.py:3 and ten.py:3-5 and ten.py:10"))
    assert [r.status for r in results] == ["verified", "verified", "verified"]


def test_a_symbol_in_the_cited_lines_is_verified(repo: Path) -> None:
    results = verify(
        repo, extract("the loader is `load_config` in src/app/config.py:4-5")
    )
    assert results[0].status == "verified"


def test_a_symbol_elsewhere_in_the_file_is_unverified_with_the_reason(
    repo: Path,
) -> None:
    results = verify(
        repo, extract("the loader is `load_config` in src/app/config.py:7-8")
    )
    assert results[0].status == "unverified"
    assert results[0].reason == "symbol load_config is not in lines 7-8"


# ---------------------------------------------------------------- 3. unverified


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("ten.py:11", "ten.py has 10 lines; line 11 does not exist"),
        ("ten.py:0", "line 0 does not exist"),
        ("ten.py:5-3", "the range 5-3 is reversed"),
        ("nope.py:1", "no such file: nope.py"),
    ],
)
def test_unverified_cases_name_the_reason(repo: Path, text: str, reason: str) -> None:
    results = verify(repo, extract(text))
    assert results[0].status == "unverified"
    assert results[0].reason == reason


def test_a_directory_is_unverified(repo: Path) -> None:
    results = verify(repo, extract("see src/app/x.py:1"))
    assert results[0].status == "unverified"
    (repo / "src" / "app" / "dir.py").mkdir()
    results = verify(repo, extract("see src/app/dir.py:1"))
    assert results[0].status == "unverified"
    assert "is a directory" in results[0].reason


# ---------------------------------------------------------------- 4. protected and hostile


PROTECTED = [
    "../etc/passwd:1",
    "/etc/passwd:1",
    "C:\\Windows\\x.py:1",
    ".env:1",
    ".git/config:1",
    ".ract/x.py:1",
]


def test_protected_and_hostile_paths_are_never_opened(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    real = citations._read_capped

    def spy(path: Path) -> bytes:
        opened.append(str(path))
        if any(part in str(path) for part in (".env", ".git", ".ract", "passwd")):
            raise AssertionError(f"a protected path was opened: {path}")
        return real(path)

    monkeypatch.setattr(citations, "_read_capped", spy)
    for text in PROTECTED:
        results = verify(repo, extract(text))
        assert results and results[0].status == "not checked", text
    assert opened == []


def test_a_symlink_out_of_the_project_is_not_opened(
    repo: Path, tmp_path_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path_factory.mktemp("outside") / "secret.py"
    outside.write_text("SECRET = 1\n", encoding="utf-8")
    link = repo / "link.py"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create a symlink here: {exc}")
    opened: list[str] = []
    monkeypatch.setattr(
        citations, "_read_capped", lambda p: opened.append(str(p)) or b""
    )
    results = verify(repo, extract("see link.py:1"))
    assert results[0].status == "not checked"
    assert opened == []


# ---------------------------------------------------------------- 5. size


def test_a_file_over_the_cap_is_too_large_to_check(repo: Path) -> None:
    big = repo / "big.py"
    big.write_bytes(b"x" * (3 * 1024 * 1024))
    results = verify(repo, extract("see big.py:1"))
    assert results[0].status == "unverified"
    assert results[0].reason == "big.py is too large to check"


# ---------------------------------------------------------------- 6. the cap on checks


def test_sixty_citations_check_fifty_and_count_the_rest(repo: Path) -> None:
    text = " ".join(f"ten.py:{(i % 10) + 1}" for i in range(60))
    results = verify(repo, extract(text))
    assert len(results) == 60
    assert (
        sum(1 for r in results if r.reason == "too many citations to check")
        == 60 - MAX_CHECKED
    )
    assert all(r.status == "verified" for r in results[:MAX_CHECKED])


# ---------------------------------------------------------------- 7. control characters


def test_control_characters_never_reach_the_reasons(repo: Path) -> None:
    text = "see `ev\x1b[31mil` in ten.py:3 and bad\x1b[2J.py:1"
    results = verify(repo, extract(text))
    for result in results:
        assert "\x1b" not in result.reason
        assert "\x1b" not in result.citation.path


# ---------------------------------------------------------------- 8. order of results


def test_results_follow_the_order_of_appearance(repo: Path) -> None:
    results = verify(repo, extract("ten.py:9 then nope.py:1 then ten.py:2"))
    assert [r.citation.path for r in results] == ["ten.py", "nope.py", "ten.py"]


def test_a_line_number_with_thousands_of_digits_is_not_checked_and_does_not_raise(
    repo: Path,
) -> None:
    text = "see src/a.py:" + "9" * 5000 + " and ten.py:2"
    results = verify(repo, extract(text))
    assert results[0].status == "not checked"
    assert results[0].reason == "src/a.py: line number too large"
    assert results[1].status == "verified"


def test_a_range_end_with_many_digits_is_not_checked(repo: Path) -> None:
    results = verify(repo, extract("see ten.py:1-" + "1" * 40))
    assert results[0].status == "not checked"
    assert "too large" in results[0].reason
