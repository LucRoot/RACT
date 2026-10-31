"""B-010a: the read-only tool slice (ADR-0047 D1, D4).

Four tier-0 tools, ``read_file``, ``list_dir``, ``glob`` and ``grep``, each a
``ToolSpec`` with a declared tier and an argument model that forbids extra keys.
Every result that would go to a model is labeled as untrusted repository content
and passes the outbound scan.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from ract.core.threat_model import CapabilityTier
from ract.tools import REGISTRY, UNTRUSTED_LABEL, ToolSpec, run_tool


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    # Bytes, so the line endings are LF on every platform.
    (root / "src" / "calc.py").write_bytes(
        b"def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n"
    )
    (root / "README.md").write_text("# calc\n", encoding="utf-8")
    return root


def _ok(result):
    assert result.is_ok(), result.error
    return result.unwrap()


# ------------------------------------------------------------------ the specs


def test_the_read_tools_are_registered_at_tier_0_and_never_mutate() -> None:
    # B-110 adds repo_map (tier 0) and the write tools, which read_only_tools() leaves out.
    from ract.tools import read_only_tools

    # B-115 adds git_status, git_diff and git_log, which read at tier 0.
    assert sorted(read_only_tools()) == [
        "git_diff",
        "git_log",
        "git_status",
        "glob",
        "grep",
        "list_dir",
        "read_file",
        "repo_map",
    ]
    for spec in read_only_tools().values():
        assert spec.tier is CapabilityTier.TIER_0_READ
        assert spec.mutates is False
        assert spec.result_cap_bytes > 0


def test_a_tier_0_spec_that_mutates_is_refused_at_definition() -> None:
    spec = REGISTRY["read_file"]
    with pytest.raises(ValueError):
        ToolSpec(
            name="bad",
            tier=CapabilityTier.TIER_0_READ,
            args_model=spec.args_model,
            mutates=True,
            result_cap_bytes=10,
            run=spec.run,
        )


def test_an_extra_argument_is_refused(ws: Path) -> None:
    result = run_tool(ws, "read_file", {"path": "README.md", "mode": "w"})
    assert not result.is_ok()
    assert "mode" in result.error


def test_an_unknown_tool_is_refused_with_the_list(ws: Path) -> None:
    result = run_tool(ws, "frobnicate", {"path": "a"})
    assert not result.is_ok()
    assert "read_file" in result.error


# ------------------------------------------------------------------ read_file


def test_read_file_gives_numbered_lines_the_digest_and_the_facts(ws: Path) -> None:
    data = (ws / "src" / "calc.py").read_bytes()
    result = _ok(run_tool(ws, "read_file", {"path": "src/calc.py"}))
    assert result.text.startswith(UNTRUSTED_LABEL)
    assert "     2\t    return a - b" in result.text
    assert result.facts["sha256"] == hashlib.sha256(data).hexdigest()
    assert result.facts["lines"] == 6
    assert result.facts["utf8"] is True and result.facts["bom"] is False
    assert result.facts["line_endings"] == "lf"
    assert result.truncated is False


def test_read_file_reads_a_line_range(ws: Path) -> None:
    result = _ok(
        run_tool(ws, "read_file", {"path": "src/calc.py", "offset": 5, "limit": 1})
    )
    assert "     5\tdef sub(a, b):" in result.text
    assert "def add" not in result.text
    assert result.truncated is True


def test_read_file_flags_a_file_that_is_not_utf8(ws: Path) -> None:
    (ws / "latin.txt").write_bytes(b"caf\xe9\r\nend\r\n")
    result = _ok(run_tool(ws, "read_file", {"path": "latin.txt"}))
    assert result.facts["utf8"] is False
    assert result.facts["line_endings"] == "crlf"


def test_read_file_gives_size_and_digest_only_for_a_binary_file(ws: Path) -> None:
    data = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
    (ws / "img.png").write_bytes(data)
    result = _ok(run_tool(ws, "read_file", {"path": "img.png"}))
    assert result.facts["binary"] is True
    assert result.facts["sha256"] == hashlib.sha256(data).hexdigest()
    assert "PNG" not in result.text.split("\n", 1)[1]


def test_read_file_marks_a_cut_at_the_byte_cap(ws: Path) -> None:
    (ws / "big.txt").write_text(
        "x" * 100 + "\n" * 0 + ("line\n" * 100_000), encoding="utf-8"
    )
    result = _ok(run_tool(ws, "read_file", {"path": "big.txt"}))
    assert result.truncated is True
    assert len(result.text.encode("utf-8")) <= REGISTRY["read_file"].result_cap_bytes


# ------------------------------------------------------------------ list_dir and glob


def _git(ws: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=ws, check=True, capture_output=True)


def test_list_dir_skips_git_and_ract_and_ignored_paths(ws: Path) -> None:
    _git(ws, "init", "-q")
    (ws / ".gitignore").write_text("build/\n", encoding="utf-8")
    (ws / "build").mkdir()
    (ws / ".ract").mkdir()
    result = _ok(run_tool(ws, "list_dir", {"path": "."}))
    names = [entry["name"] for entry in result.facts["entries"]]
    assert ".git" not in names and ".ract" not in names and "build" not in names
    assert "src" in names and "README.md" in names
    every = _ok(run_tool(ws, "list_dir", {"path": ".", "include_ignored": True}))
    assert "build" in [e["name"] for e in every.facts["entries"]]
    assert ".git" not in [e["name"] for e in every.facts["entries"]]


def test_glob_matches_across_folders_and_skips_ract(ws: Path) -> None:
    (ws / ".ract").mkdir()
    (ws / ".ract" / "x.py").write_text("x", encoding="utf-8")
    result = _ok(run_tool(ws, "glob", {"pattern": "**/*.py"}))
    assert result.facts["paths"] == ["src/calc.py"]


# ------------------------------------------------------------------ grep


def test_grep_finds_lines_with_file_and_line_number(ws: Path) -> None:
    result = _ok(run_tool(ws, "grep", {"pattern": r"return a - b"}))
    found = {(m["path"], m["line"]) for m in result.facts["matches"]}
    assert found == {("src/calc.py", 2), ("src/calc.py", 6)}


def test_grep_python_fallback_gives_the_same_matches(
    ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ract.tools.read._ripgrep", lambda root: None)
    result = _ok(run_tool(ws, "grep", {"pattern": r"return a - b"}))
    found = {(m["path"], m["line"]) for m in result.facts["matches"]}
    assert found == {("src/calc.py", 2), ("src/calc.py", 6)}
    assert result.facts["engine"] == "python"


def test_a_secret_in_a_file_is_redacted_before_it_reaches_the_model(ws: Path) -> None:
    token = "sk-" + "a1b2c3d4e5f6" * 4
    (ws / "settings.py").write_text(f'OPENAI_API_KEY = "{token}"\n', encoding="utf-8")
    result = _ok(run_tool(ws, "read_file", {"path": "settings.py"}))
    assert token not in result.text
    assert result.facts["redacted"]
