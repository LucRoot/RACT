"""ADR-0048 D4: the command-matching bypass corpus, one row per case.

Nothing runs: the PATH is a temporary folder of placeholder files, so
``shutil.which`` resolves names and no command executes. Each row states the
expected outcome: refused, asks, or matches.
"""

from __future__ import annotations

import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ract.policy.grant import parse_policy
from ract.policy.matcher import classify

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
TOOLS = [
    "pytest",
    "git",
    "python",
    "node",
    "find",
    "xargs",
    "sh",
    "bash",
    "twine",
    "npm",
    "make",
    "env",
    "timeout",
    "ract",
]


@pytest.fixture
def world(tmp_path: Path):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "pytest").write_text("planted shim", encoding="utf-8")
    (project / "scripts" / "build.sh").write_text("echo hi", encoding="utf-8")
    (project / "conftest_plugin.py").write_text("x = 1", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in TOOLS:
        name = f"{tool}.exe" if os.name == "nt" else tool
        if tool == "npm" and os.name == "nt":
            name = "npm.cmd"
        path = bin_dir / name
        path.write_text("", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    # The project's own folder is on PATH too: the scrubbed PATH drops it.
    path_env = os.pathsep.join([str(project), str(bin_dir)])
    policy = parse_policy(
        "version: 1\n"
        f"binding:\n  project_root: '{os.path.realpath(project)}'\n"
        f"issued_at: {NOW:%Y-%m-%dT%H:%M:%SZ}\n"
        f"expires_at: {NOW + timedelta(days=30):%Y-%m-%dT%H:%M:%SZ}\n"
        "key_id: ed25519:0123456789abcdef\n"
        "sandbox: best_effort\n"
        "commands:\n"
        "  allow:\n"
        "    - id: tests\n"
        "      argv: [python, -m, pytest]\n"
        "      env_extra: [PYTHONHASHSEED]\n"
        "    - id: pytest\n"
        "      argv: [pytest]\n"
        "    - id: status\n"
        "      argv: [git, status]\n"
        "    - id: show\n"
        "      argv: [git, show]\n"
        "  deny:\n"
        "    - argv: [git, reset, --hard]\n"
    )
    return project, policy, path_env


ROWS = [
    # (argv, expected outcome, a word the reason holds)
    (["python", "-m", "pytest", "-k", "add"], "matches", "tests"),
    (["pytest", "tests/test_calc.py"], "matches", "pytest"),
    (["python", "-m", "pytest", "-c", "setup.cfg"], "matches", "tests"),  # pytest's -c
    (["pytest-evil"], "refused", "not found"),  # a substring name
    (["./pytest"], "asks", "no rule"),  # the planted shim: repository code
    (["git", "status"], "matches", "status"),
    (["git", "-c", "alias.x=!sh", "status"], "asks", "global options"),
    (["git", "-C", "..", "status"], "asks", "global options"),
    (["git", "show", "--output=/tmp/x", "HEAD"], "asks", "output"),
    (["git", "push"], "asks", "remote git"),
    # G-239 D12: remote plumbing and archive --remote ask too.
    (["git", "send-pack", "x", "main"], "asks", "remote git"),
    (["git", "fetch-pack", "x"], "asks", "remote git"),
    (["git", "http-push", "x"], "asks", "remote git"),
    (["git", "archive", "--remote=x", "HEAD"], "asks", "remote git"),
    (["git", "archive", "--remote", "x", "HEAD"], "asks", "remote git"),
    (["git", "submodule", "update"], "asks", "remote git"),
    (["git", "reset", "--hard"], "refused", "denied"),
    (["sh", "-c", "pytest"], "refused", "shell"),
    (["bash", "-lc", "pytest"], "refused", "shell"),
    (["python", "-c", "import os"], "refused", "inline code"),
    (["node", "-e", "1"], "refused", "inline code"),
    (
        ["env", "LD_PRELOAD=/x.so", "python", "-m", "pytest"],
        "asks",
        "environment variable",
    ),
    (["env", "PYTHONHASHSEED=0", "python", "-m", "pytest"], "matches", "tests"),
    (["env", "-i", "python", "-m", "pytest"], "refused", "env options"),
    (["timeout", "30", "python", "-m", "pytest"], "matches", "tests"),
    (["xargs", "rm"], "refused", "never matches"),
    (["find", ".", "-exec", "rm", "{}", ";"], "refused", "find with -exec"),
    (["find", ".", "-delete"], "refused", "find with -exec"),
    (["twine", "upload", "dist/*"], "refused", "publishes"),
    (["ract", "policy", "sign"], "refused", "governance"),
    (
        ["python", "-m", "ract.cli", "handshakes", "approve", "m1"],
        "refused",
        "governance",
    ),
    (["pуtest"], "refused", "ASCII"),  # Cyrillic u
    (["make", "test"], "asks", "no rule"),
    (["scripts/build.sh"], "asks", "no rule"),
    (["pytest", "-p", "conftest_plugin"], "asks", "plugin"),
    (["../outside/tool"], "refused", "outside the project"),
    ([], "refused", "empty"),
]


@pytest.mark.parametrize(
    ("argv", "outcome", "word"), ROWS, ids=[" ".join(r[0]) or "empty" for r in ROWS]
)
def test_the_corpus(world, argv, outcome, word) -> None:
    project, policy, path_env = world
    result = classify(argv, policy, project, path_env=path_env)
    assert result.outcome == outcome, result
    assert word.lower() in result.reason.lower(), result


def test_a_planted_shim_does_not_satisfy_the_pytest_rule(world) -> None:
    project, policy, path_env = world
    result = classify(["pytest"], policy, project, path_env=path_env)
    assert result.outcome == "matches"
    assert not result.executable.startswith(
        str(project)
    )  # the shim on PATH was skipped
    shim = classify(["./pytest"], policy, project, path_env=path_env)
    assert shim.repository_code and "it runs repository code" in shim.notes


def test_a_file_the_model_wrote_always_asks(world) -> None:
    project, policy, path_env = world
    result = classify(
        ["python", "-m", "pytest", "tests/test_new.py"],
        policy,
        project,
        path_env=path_env,
        model_written=frozenset({"tests/test_new.py"}),
    )
    assert result.outcome == "asks" and "written in this session" in result.reason


@pytest.mark.skipif(os.name != "nt", reason="npm.cmd is the Windows form")
@pytest.mark.parametrize("arg", ["a&b", "50%", 'x"y', "a^b"])
def test_a_cmd_target_with_an_unplain_argument_is_refused(world, arg: str) -> None:
    project, policy, path_env = world
    result = classify(["npm", "test", arg], policy, project, path_env=path_env)
    assert result.outcome == "refused" and "cmd.exe" in result.reason
