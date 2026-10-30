"""G-214 (the MANAGER's senior review, part 2): M1, M2, M3, T1, T2, and G-213 G2.

Each row is a bypass the review found or a form of it. Nothing runs: the PATH
is a folder of placeholder files, as in the D4 corpus.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ract.policy.grant import PolicyInvalid, parse_policy
from ract.policy.matcher import classify, resolve_executable
from tests.security.test_command_matching_corpus import world  # noqa: F401 (fixture)

M1 = [
    ["python", "-X", "utf8", "-c", "import os"],
    ["python", "-W", "ignore", "-c", "1"],
    ["python", "-Ic", "1"],
    ["python", "-Sc", "1"],
    ["python", "-I", "-c", "1"],
    ["python3.11", "-c", "1"],
    ["python3.12", "-c", "1"],
    ["pythonw", "-c", "1"],
    ["node", "--eval=1"],
    ["node", "-pe", "1"],
    ["node", "-r", "x", "-e", "1"],
    ["perl", "-le", "print 1"],
    ["perl", "-ne", "print"],
    ["ruby", "-ne", "p 1"],
    ["bun", "-e", "1"],
    ["php", "-r", "echo 1;"],
    ["lua", "-e", "print(1)"],
    ["Rscript", "-e", "1"],
    ["osascript", "-e", "beep"],
    ["awk", 'BEGIN{system("id")}'],
    ["sed", "1e id", "f"],
    ["deno", "eval", "1"],
]

M2 = [
    ["flock", "x", "bash", "-c", "id"],
    ["setsid", "sh", "-c", "id"],
    ["taskset", "1", "python", "-c", "1"],
    ["strace", "python", "-c", "1"],
    ["xvfb-run", "bash", "-c", "id"],
    ["chroot", "/", "sh"],
]


@pytest.mark.parametrize("argv", M1, ids=[" ".join(a) for a in M1])
def test_m1_inline_code_is_refused_in_every_form(world, argv) -> None:  # noqa: F811
    project, policy, path_env = world
    result = classify(argv, policy, project, path_env=path_env)
    assert result.outcome == "refused" and "inline code" in result.reason, result


@pytest.mark.parametrize("argv", M2, ids=[" ".join(a) for a in M2])
def test_m2_a_wrapped_shell_or_interpreter_is_refused(world, argv) -> None:  # noqa: F811
    project, policy, path_env = world
    result = classify(argv, policy, project, path_env=path_env)
    assert result.outcome == "refused" and "shell mode" in result.reason, result


@pytest.mark.parametrize(
    "argv",
    [
        ["python", "-m", "pytest", "-c", "setup.cfg"],
        ["python", "-X", "dev", "-m", "pytest"],
        ["python", "-m", "pytest", "-p", "no:cacheprovider", "-W", "error"],
    ],
)
def test_m1_the_runners_own_options_still_match(world, argv) -> None:  # noqa: F811
    project, policy, path_env = world
    # Not the floor: the runner's options are not inline code. (A prefix that
    # differs from the rule asks, as any unmatched command does.)
    result = classify(argv, policy, project, path_env=path_env)
    assert result.outcome != "refused", result


@pytest.mark.skipif(os.name != "nt", reason="Windows searches the current folder first")
def test_m3_a_planted_shim_in_the_cwd_or_worktree_is_never_chosen(
    tmp_path: Path, monkeypatch
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    for name in ("zzshim.cmd", "zzshim.exe"):
        (worktree / name).write_text("", encoding="utf-8")
    monkeypatch.chdir(worktree)
    system = os.environ.get("SystemRoot", r"C:\Windows")
    assert resolve_executable("zzshim", system, [worktree]) is None
    # A real program on the PATH is found, absolute.
    found = resolve_executable("cmd", os.path.join(system, "System32"), [worktree])
    assert found and os.path.isabs(found)


def test_m3_a_relative_path_entry_and_a_link_into_the_project_are_skipped(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    (project / "bin").mkdir(parents=True)
    name = "tool.exe" if os.name == "nt" else "tool"
    (project / "bin" / name).write_text("", encoding="utf-8")
    os.chmod(project / "bin" / name, 0o755)
    assert resolve_executable("tool", "bin", [project]) is None  # relative entry
    assert resolve_executable("tool", str(project / "bin"), [project]) is None


def _policy(argv: str) -> str:
    return (
        "version: 1\n"
        "binding:\n  project_root: 'x'\n"
        "issued_at: 2026-10-30T10:00:00Z\n"
        "expires_at: 2026-11-30T10:00:00Z\n"
        "key_id: ed25519:0123456789abcdef\n"
        "sandbox: best_effort\n"
        f"commands:\n  allow:\n    - id: r\n      argv: {argv}\n"
    )


@pytest.mark.parametrize(
    "argv",
    [
        "[python, -c]",
        "[bash, -c]",
        "[node, -e]",
        "[powershell, -Command]",
        "[env, python]",
        "[xargs, rm]",
        "[timeout, '30', python]",
        "[uv, run]",
        "[npx, jest]",
        "[python, -m, pip]",
        "[python, -m, runpy]",
        "[flock, x, pytest]",
    ],
)
def test_g2_rules_that_could_never_be_narrow_are_refused_at_load(argv: str) -> None:
    with pytest.raises(PolicyInvalid):
        parse_policy(_policy(argv))


@pytest.mark.parametrize(
    "argv", ["[python, -m, pytest]", "[pytest]", "[npm, test]", "[make, test]"]
)
def test_g2_narrow_rules_still_load(argv: str) -> None:
    parse_policy(_policy(argv))


def test_t2_the_prompt_names_the_project_code_written_this_session() -> None:
    from ract.tools.tests_tool import _project_code_notes

    notes = _project_code_notes({"tests/conftest.py", "src/calc.py", "pyproject.toml"})
    assert notes[0].startswith("this runs project code")
    assert "written in this session: pyproject.toml, tests/conftest.py" in notes[0]
    assert "src/calc.py" not in notes[0]
