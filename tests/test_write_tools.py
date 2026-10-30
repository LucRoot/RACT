"""B-110 D1: the write tools and repo_map (ADR-0047 D1, D3, D4).

Hostile cases first: protected paths, digests the model did not read, a file
that is not clean UTF-8, a patch that half-applies, a path that leaves the
project, and a write tool reaching the read-only answer loop. Then the tier
of every tool and every call, and what each tool does.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ract.core.threat_model import CapabilityTier
from ract.tools import REGISTRY, read_only_tools, run_tool
from ract.tools.write import call_tier, path_tier

T0, T1, T2 = (
    CapabilityTier.TIER_0_READ,
    CapabilityTier.TIER_1_WRITE,
    CapabilityTier.TIER_2_ENV,
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    return root


def _run(root: Path, name: str, **args):
    return run_tool(root, name, args)


# --- hostile cases ---------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ".git/config",
        ".ract/policy.yaml",
        ".claude/settings.json",
        "sub/.agents/x.md",
        ".cursor/rules",
    ],
)
def test_protected_paths_are_refused_for_every_write_tool(
    project: Path, path: str
) -> None:
    result = _run(project, "write_file", path=path, content="x = 1\n", create=True)
    assert not result.is_ok() and "refused" in (result.error or "")
    assert not (project / path).exists()


def test_an_existing_file_needs_the_digest_it_has_now(project: Path) -> None:
    calc = project / "src" / "calc.py"
    before = calc.read_bytes()
    missing = _run(project, "write_file", path="src/calc.py", content="x = 1\n")
    stale = _run(
        project,
        "edit_file",
        path="src/calc.py",
        old="a - b",
        new="a + b",
        expected_digest="0" * 64,
    )
    assert "expected_digest" in (missing.error or "")
    assert "changed since it was read" in (stale.error or "")
    assert stale.hint == "re-read the file; it changed since your last read"
    assert calc.read_bytes() == before


def test_create_refuses_an_existing_file_and_a_new_file_needs_create(
    project: Path,
) -> None:
    assert "create refuses it" in (
        _run(
            project, "write_file", path="src/calc.py", content="x\n", create=True
        ).error
        or ""
    )
    assert "pass create=true" in (
        _run(project, "write_file", path="src/new.py", content="x\n").hint or ""
    )
    assert not (project / "src" / "new.py").exists()


def test_an_empty_body_is_refused(project: Path) -> None:
    result = _run(project, "write_file", path="src/new.py", content="  \n", create=True)
    assert "empty body" in (result.error or "")


def test_a_file_that_is_not_utf8_is_not_edited(project: Path) -> None:
    latin = project / "src" / "latin.txt"
    latin.write_bytes(b"caf\xe9\n")
    result = _run(
        project,
        "edit_file",
        path="src/latin.txt",
        old="caf",
        new="tea",
        expected_digest=_digest(latin),
    )
    assert "not clean UTF-8" in (result.error or "")
    assert latin.read_bytes() == b"caf\xe9\n"


@pytest.mark.parametrize("path", ["../outside.py", "src/../../outside.py"])
def test_a_path_out_of_the_project_is_refused(project: Path, path: str) -> None:
    assert not _run(
        project, "write_file", path=path, content="x\n", create=True
    ).is_ok()
    assert not (project.parent / "outside.py").exists()


def test_a_patch_that_fails_on_its_second_file_changes_nothing(project: Path) -> None:
    (project / "src" / "b.py").write_text("one\ntwo\n", encoding="utf-8")
    patch = (
        "--- a/src/calc.py\n+++ b/src/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"
        "--- a/src/b.py\n+++ b/src/b.py\n@@ -1,2 +1,2 @@\n one\n-NOT THERE\n+three\n"
    )
    before = (project / "src" / "calc.py").read_bytes()
    result = _run(project, "apply_patch", patch=patch)
    assert not result.is_ok() and "does not match" in (result.error or "")
    assert (project / "src" / "calc.py").read_bytes() == before


def test_a_patch_touching_a_protected_path_is_refused_whole(project: Path) -> None:
    patch = (
        "--- a/src/calc.py\n+++ b/src/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"
        "--- /dev/null\n+++ b/.git/hooks/pre-commit\n@@ -0,0 +1 @@\n+echo pwned\n"
    )
    before = (project / "src" / "calc.py").read_bytes()
    assert not _run(project, "apply_patch", patch=patch).is_ok()
    assert (project / "src" / "calc.py").read_bytes() == before


def test_the_read_only_loop_never_offers_a_write_tool() -> None:
    from ract.tools import loop

    offered = set(read_only_tools())
    assert offered == {"read_file", "list_dir", "glob", "grep", "repo_map"}
    assert "write_file" not in loop.tool_lines()
    from ract.executor.tool_gate import ToolInvocationRefused

    gate = loop._gate(Path("."), loop.LoopBudgets())
    with pytest.raises(ToolInvocationRefused):
        gate.invoke("write_file", {"path": "x.py", "content": "x\n", "create": True})
    assert not Path("x.py").exists()


# --- tiers ------------------------------------------------------------------


def test_every_registered_tool_has_its_tier_pinned() -> None:
    pinned = {
        "read_file": T0,
        "list_dir": T0,
        "glob": T0,
        "grep": T0,
        "repo_map": T0,
        "write_file": T1,
        "edit_file": T1,
        "delete_file": T1,
        "move_file": T1,
        "apply_patch": T1,
        # B-112: runs a command under the grant's test rule, asked first.
        "run_tests": CapabilityTier.TIER_3_EXTERNAL,
    }
    assert {name: spec.tier for name, spec in REGISTRY.items()} == pinned
    for spec in REGISTRY.values():
        assert spec.mutates == (spec.tier is not T0)


@pytest.mark.parametrize(
    ("path", "tier"),
    [
        ("src/app.py", T1),
        ("AGENTS.md", T2),
        ("docs/CLAUDE.md", T2),
        ("RACT.md", T2),
        ("prompts/manager.txt", T2),
        (".github/workflows/ci.yml", T2),
        (".vscode/tasks.json", T2),
        (".envrc", T2),
        (".pre-commit-config.yaml", T2),
        (".venv/Scripts/activate", T2),
    ],
)
def test_a_control_or_executable_configuration_path_is_tier_2(
    project: Path, path: str, tier
) -> None:
    assert path_tier(project, path) is tier


def test_a_folder_with_pyvenv_cfg_is_a_virtual_environment(project: Path) -> None:
    (project / "env").mkdir()
    (project / "env" / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    assert path_tier(project, "env/bin/python") is T2


def test_a_call_takes_the_highest_tier_of_its_paths(project: Path) -> None:
    from ract.tools.write import ApplyPatchArgs, MoveFileArgs

    move = MoveFileArgs(
        path="src/calc.py", destination="AGENTS.md", expected_digest="0" * 64
    )
    assert call_tier(REGISTRY["move_file"], move, project) is T2
    patch = ApplyPatchArgs(
        patch="--- /dev/null\n+++ b/src/x.py\n@@ -0,0 +1 @@\n+x = 1\n"
        "--- /dev/null\n+++ b/.github/workflows/ci.yml\n@@ -0,0 +1 @@\n+on: push\n"
    )
    assert call_tier(REGISTRY["apply_patch"], patch, project) is T2


# --- what each tool does -----------------------------------------------------


def test_edit_file_replaces_once_and_reports_the_digests(project: Path) -> None:
    calc = project / "src" / "calc.py"
    before = _digest(calc)
    result = _run(
        project,
        "edit_file",
        path="src/calc.py",
        old="a - b",
        new="a + b",
        expected_digest=before,
    )
    assert result.is_ok(), result.error
    assert "return a + b" in calc.read_text(encoding="utf-8")
    facts = result.unwrap().facts
    assert facts["digest_before"] == before and facts["digest_after"] == _digest(calc)


def test_edit_file_refuses_a_text_that_occurs_twice(project: Path) -> None:
    calc = project / "src" / "calc.py"
    calc.write_text("x = 1\nx = 1\n", encoding="utf-8")
    result = _run(
        project,
        "edit_file",
        path="src/calc.py",
        old="x = 1",
        new="x = 2",
        expected_digest=_digest(calc),
    )
    assert "occurs 2 times" in (result.error or "")
    both = _run(
        project,
        "edit_file",
        path="src/calc.py",
        old="x = 1",
        new="x = 2",
        expected_digest=_digest(calc),
        replace_all=True,
    )
    assert both.is_ok() and calc.read_text(encoding="utf-8") == "x = 2\nx = 2\n"


def test_an_edit_keeps_the_bom_and_the_line_endings(project: Path) -> None:
    f = project / "src" / "win.txt"
    f.write_bytes(b"\xef\xbb\xbfone\r\ntwo\r\n")
    result = _run(
        project,
        "edit_file",
        path="src/win.txt",
        old="two",
        new="three",
        expected_digest=_digest(f),
    )
    assert result.is_ok(), result.error
    assert f.read_bytes() == b"\xef\xbb\xbfone\r\nthree\r\n"


def test_write_delete_and_move(project: Path) -> None:
    assert _run(
        project, "write_file", path="src/new.py", content="X = 1\n", create=True
    ).is_ok()
    new = project / "src" / "new.py"
    assert _run(
        project,
        "move_file",
        path="src/new.py",
        destination="lib/new.py",
        expected_digest=_digest(new),
    ).is_ok()
    moved = project / "lib" / "new.py"
    assert moved.read_text(encoding="utf-8") == "X = 1\n" and not new.exists()
    calc = project / "src" / "calc.py"
    refused = _run(
        project,
        "move_file",
        path="lib/new.py",
        destination="src/calc.py",
        expected_digest=_digest(moved),
    )
    assert "refuses it" in (refused.error or "")
    assert _run(
        project, "delete_file", path="lib/new.py", expected_digest=_digest(moved)
    ).is_ok()
    assert not moved.exists() and calc.exists()


def test_apply_patch_creates_changes_and_deletes(project: Path) -> None:
    (project / "src" / "old.py").write_text("gone\n", encoding="utf-8")
    patch = (
        "--- a/src/calc.py\n+++ b/src/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"
        "--- /dev/null\n+++ b/src/notes.py\n@@ -0,0 +1,2 @@\n+NOTE = 1\n+OTHER = 2\n"
        "--- a/src/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-gone\n"
    )
    result = _run(project, "apply_patch", patch=patch)
    assert result.is_ok(), result.error
    assert "return a + b" in (project / "src" / "calc.py").read_text(encoding="utf-8")
    assert (project / "src" / "notes.py").read_text(
        encoding="utf-8"
    ) == "NOTE = 1\nOTHER = 2\n"
    assert not (project / "src" / "old.py").exists()


def test_repo_map_lists_files_and_top_level_names(project: Path) -> None:
    (project / ".git").mkdir()
    (project / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (project / "src" / "shapes.py").write_text(
        "class Square:\n    pass\n\ndef area(s):\n    return s\n", encoding="utf-8"
    )
    result = _run(project, "repo_map")
    assert result.is_ok(), result.error
    text = result.unwrap().text
    assert "src/calc.py: add" in text and "src/shapes.py: Square, area" in text
    assert ".git" not in text


# --- the tier gate in run_tool ---------------------------------------------


def test_a_tier_2_write_needs_the_operators_approval(project: Path) -> None:
    refused = _run(
        project, "write_file", path="AGENTS.md", content="be nice\n", create=True
    )
    assert not refused.is_ok() and "tier 2" in (refused.error or "")
    assert not (project / "AGENTS.md").exists()
    asked: list[str] = []

    def operator(name, args) -> bool:
        asked.append(name)
        return True

    allowed = run_tool(
        project,
        "write_file",
        {"path": "AGENTS.md", "content": "be nice\n", "create": True},
        approve_tier_2=operator,
    )
    assert allowed.is_ok() and asked == ["write_file"]
    assert allowed.unwrap().facts["tier"] == "T2"


def test_a_tier_1_write_reports_its_tier(project: Path) -> None:
    result = _run(
        project, "write_file", path="src/n.py", content="N = 1\n", create=True
    )
    assert result.is_ok() and result.unwrap().facts["tier"] == "T1"
