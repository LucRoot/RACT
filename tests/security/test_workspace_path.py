"""Red-team tests for the workspace path resolver (ADR-0047 D2, board S-001).

Every way a model-supplied path has escaped a project in comparable tools has
a row here. The Windows string rules are exercised on every platform through
``windows=True``; tests that need a real Windows or POSIX filesystem feature
say so in their skip reason.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ract.diff_applier import DiffApplier
from ract.workspace_path import (
    WorkspacePathRefused,
    require_workspace_path,
    resolve_workspace_path,
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (root / ".git" / "hooks").mkdir(parents=True)
    (root / ".ract" / "hooks").mkdir(parents=True)
    return root


def _code(
    root: Path, raw: str, *, purpose: str = "read", windows: bool | None = None
) -> str:
    result = resolve_workspace_path(root, raw, purpose=purpose, windows=windows)  # type: ignore[arg-type]
    if result.value is not None:
        return "ok"
    assert result.hint, "every refusal carries a hint"
    return result.provenance[-1].removeprefix("refused:")


# ---------------------------------------------------------------- accepted


@pytest.mark.parametrize(
    "raw", ["src/app.py", "src\\app.py", "./src/app.py", "new/dir/file.txt"]
)
def test_ordinary_relative_paths_are_accepted(project: Path, raw: str) -> None:
    result = resolve_workspace_path(project, raw, purpose="write", windows=False)
    assert result.is_ok(), result.error
    assert result.value is not None
    assert str(result.value).startswith(os.path.realpath(project))


def test_absolute_path_inside_root_is_accepted(project: Path) -> None:
    inside = str(project / "src" / "app.py")
    assert require_workspace_path(project, inside) == Path(os.path.realpath(inside))


# ---------------------------------------------------------------- string rules, all platforms


@pytest.mark.parametrize(
    "raw, code",
    [
        ("", "empty"),
        ("   ", "empty"),
        ("src/a\x00.py", "control_character"),
        ("src/a\n.py", "control_character"),
        ("../outside.txt", "parent_segment"),
        ("src/../../outside.txt", "parent_segment"),
        ("src/../app.py", "parent_segment"),  # lands inside, still refused
        ("..\\outside.txt", "parent_segment"),
        ("/proc/self/root/etc/passwd", "proc_synonym"),
        ("/proc/1/cwd", "proc_synonym"),
    ],
)
def test_string_rules_refuse(project: Path, raw: str, code: str) -> None:
    assert _code(project, raw, windows=False) == code
    assert _code(project, raw, windows=True) == code


def test_absolute_path_outside_root_is_refused(project: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere.txt"
    assert _code(project, str(outside)) == "outside_root"


def test_sibling_with_shared_prefix_is_outside(project: Path, tmp_path: Path) -> None:
    sibling = tmp_path / "project-evil" / "x.txt"
    sibling.parent.mkdir()
    assert _code(project, str(sibling)) == "outside_root"


def test_root_itself_is_refused(project: Path) -> None:
    assert _code(project, ".") == "is_root"


# ---------------------------------------------------------------- Windows string rules


@pytest.mark.parametrize(
    "raw, code",
    [
        ("C:foo.txt", "drive_relative"),
        ("\\\\server\\share\\x.txt", "unc_or_device"),
        ("//server/share/x.txt", "unc_or_device"),
        ("\\\\?\\C:\\Windows\\x.txt", "unc_or_device"),
        ("\\\\.\\PhysicalDrive0", "unc_or_device"),
        ("src/CON", "reserved_device_name"),
        ("src/nul.txt", "reserved_device_name"),
        ("COM1.log", "reserved_device_name"),
        ("lpt9", "reserved_device_name"),
        ("src/app.py:hidden", "alternate_data_stream"),
        ("src/app.py::$DATA", "alternate_data_stream"),
        ("src/app.py.", "trailing_dot_or_space"),
        ("src/app.py ", "trailing_dot_or_space"),
        ("GIT~1/config", "short_name"),
        ("src/PROGRA~1.TXT", "short_name"),
    ],
)
def test_windows_rules_refuse(project: Path, raw: str, code: str) -> None:
    assert _code(project, raw, windows=True) == code


def test_windows_names_are_ordinary_files_on_posix_rules(project: Path) -> None:
    # A file named "con.txt" is legal on Linux and macOS.
    assert _code(project, "src/con.txt", windows=False) == "ok"


# ---------------------------------------------------------------- protected directories


@pytest.mark.parametrize(
    "raw",
    [
        ".git/hooks/pre-commit",
        ".git/config",
        ".GIT/config",
        ".ract/hooks/pre_x.json",
        ".Ract/operator.key",
        "vendor/sub/.git/hooks/post-checkout",
    ],
)
def test_writes_into_git_and_ract_are_refused(project: Path, raw: str) -> None:
    assert _code(project, raw, purpose="write", windows=False) == "protected_directory"


def test_reads_under_git_are_not_refused_by_the_resolver(project: Path) -> None:
    # Read policy for .git and .ract belongs to the tool layer (ADR-0047 D3).
    assert _code(project, ".git/hooks", purpose="read", windows=False) == "ok"


# ---------------------------------------------------------------- links


def _symlink(link: Path, target: Path, *, directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks not available here: {exc}")


def test_symlink_leading_outside_is_refused_for_read_and_write(
    project: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "key.txt").write_text("k", encoding="utf-8")
    _symlink(project / "link", outside, directory=True)
    assert _code(project, "link/key.txt", purpose="read") == "escapes_root"
    assert _code(project, "link/key.txt", purpose="write") == "symlink_in_path"


def test_symlink_inside_root_is_readable_and_never_written_through(
    project: Path,
) -> None:
    _symlink(project / "alias", project / "src", directory=True)
    assert _code(project, "alias/app.py", purpose="read") == "ok"
    assert _code(project, "alias/app.py", purpose="write") == "symlink_in_path"


def test_symlinked_file_is_not_written_through(project: Path) -> None:
    _symlink(project / "src" / "link.py", project / "src" / "app.py", directory=False)
    assert _code(project, "src/link.py", purpose="write") == "symlink_in_path"


@pytest.mark.skipif(sys.platform != "win32", reason="junctions exist only on Windows")
def test_junction_leading_outside_is_refused(project: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside_dir"
    outside.mkdir()
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(project / "junc"), str(outside)],
        capture_output=True,
        text=True,
    )
    if made.returncode != 0:
        pytest.skip(f"mklink /J failed: {made.stderr.strip()}")
    assert _code(project, "junc/x.txt", purpose="read") == "escapes_root"
    assert _code(project, "junc/x.txt", purpose="write") == "symlink_in_path"


def test_require_raises_with_refusal_details(project: Path) -> None:
    with pytest.raises(WorkspacePathRefused) as info:
        require_workspace_path(project, "../x", purpose="write")
    assert info.value.refusal.code == "parent_segment"
    assert "'..'" in str(info.value)
    assert info.value.refusal.hint


# ---------------------------------------------------------------- the two fixed call sites


def _diff(path_a: str, path_b: str) -> str:
    return f"--- {path_a}\n+++ {path_b}\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"


@pytest.mark.parametrize(
    "header",
    [
        "b/../outside.py",
        "/etc/passwd",
        "b/.git/hooks/pre-commit",
        "b/.ract/hooks/pre_x.json",
    ],
)
def test_diff_headers_cannot_leave_the_project_or_enter_protected_dirs(
    project: Path, tmp_path: Path, header: str
) -> None:
    (tmp_path / "outside.py").write_text("x = 1\n", encoding="utf-8")
    applier = DiffApplier(project)
    results = applier.apply_diff(_diff("a/src/app.py", header))
    assert results and not any(r.applied for r in results)
    assert "path refused" in results[0].message
    assert (tmp_path / "outside.py").read_text(encoding="utf-8") == "x = 1\n"


def test_diff_git_header_path_is_resolved(project: Path) -> None:
    diff = "diff --git a/src/app.py b/../evil.py\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"
    results = DiffApplier(project).apply_diff(diff)
    assert results and not results[0].applied


def test_valid_diff_still_applies(project: Path) -> None:
    results = DiffApplier(project).apply_diff(_diff("a/src/app.py", "b/src/app.py"))
    assert [r.applied for r in results] == [True]
    assert (project / "src" / "app.py").read_text(encoding="utf-8") == "x = 2\n"
