"""G-239: hostile inputs against the git tools, in temporary local repositories.

Each test is one way around the secret scan, one piece of repository config
that could run a program, or one place git could run outside the project.
Nothing reaches a remote and no real key is used: the key-shaped values are
built from pieces.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from ract.policy.matcher import classify
from ract.tools import ToolRefused, run_tool
from ract.tools import git_tools
from ract.tools.git_tools import AddArgs, git_argv, question_lines

KEY = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def _init(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Test Author")
    _git(root, "config", "user.email", "author@example.invalid")
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = _init(tmp_path / "repo")
    (root / "a.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "first")
    return root


def _yes(name, args):
    return True


def _head_subject(repo: Path) -> str:
    return _git(repo, "log", "-1", "--format=%s").strip()


def _commit_refused(repo: Path, staged: dict[str, bytes], word: str) -> str:
    for name, data in staged.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        _git(repo, "add", "-f", "--", name)
    rooted = run_tool(repo, "git_commit", {"message": "m"}, approve_tier_2=_yes)
    assert not rooted.is_ok(), "the commit went on"
    assert word in rooted.error, rooted.error
    assert _head_subject(repo) == "first"
    return rooted.error


# ---------------------------------------------------------------- A: the secret scan


def test_a1_a_line_that_starts_with_two_plus_signs_is_scanned(repo: Path) -> None:
    error = _commit_refused(
        repo, {"cfg.py": f'++API_KEY="{KEY}"\n'.encode()}, "cfg.py:1"
    )
    assert KEY not in error


def test_a1_a_plus_plus_line_does_not_reset_the_path(repo: Path) -> None:
    body = f"++ x\nKEY = '{KEY}'\n".encode()
    _commit_refused(repo, {"one.py": body}, "one.py:2")


def test_a2_a_file_with_a_nul_byte_is_scanned(repo: Path) -> None:
    _commit_refused(
        repo, {"blob.bin": b"\x00\x01" + KEY.encode() + b"\n"}, "blob.bin:1"
    )


def test_a2_a_path_marked_minus_diff_is_scanned(repo: Path) -> None:
    (repo / ".gitattributes").write_text("secret.txt -diff\n", encoding="utf-8")
    _git(repo, "add", ".gitattributes")
    _commit_refused(repo, {"secret.txt": f"{KEY}\n".encode()}, "secret.txt:1")


def test_a2_a_file_over_the_big_file_threshold_is_scanned(repo: Path) -> None:
    _git(repo, "config", "core.bigFileThreshold", "1k")
    body = b"x = 1\n" * 400 + f"KEY = '{KEY}'\n".encode()
    _commit_refused(repo, {"big.py": body}, "big.py:401")


def test_a2_a_utf16_file_is_scanned(repo: Path) -> None:
    body = f"KEY = '{KEY}'\n".encode("utf-16")
    _commit_refused(repo, {"wide.txt": body}, "wide.txt:1")


def test_a3_the_scan_refuses_when_git_fails(repo: Path, monkeypatch) -> None:
    real = git_tools._run

    def failing(root, argv, **kwargs):
        if "--raw" in argv:
            return git_tools._Done(128, b"", b"fatal: broken index")
        return real(root, argv, **kwargs)

    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    monkeypatch.setattr(git_tools, "_run", failing)
    rooted = run_tool(repo, "git_commit", {"message": "m"}, approve_tier_2=_yes)
    assert not rooted.is_ok() and "could not list the staged files" in rooted.error
    assert _head_subject(repo) == "first"


def test_a3_the_scan_refuses_when_the_blobs_cannot_be_read(
    repo: Path, monkeypatch
) -> None:
    real = git_tools._run

    def failing(root, argv, **kwargs):
        if "--batch" in argv:
            return git_tools._Done(128, b"", b"fatal: bad object")
        return real(root, argv, **kwargs)

    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    monkeypatch.setattr(git_tools, "_run", failing)
    rooted = run_tool(repo, "git_commit", {"message": "m"}, approve_tier_2=_yes)
    assert not rooted.is_ok() and "could not read the staged files" in rooted.error
    assert _head_subject(repo) == "first"


def test_a3_a_change_over_the_scan_cap_refuses(repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(git_tools, "_SCAN_CAP", 1024)
    _commit_refused(repo, {"big.txt": b"y" * 4096}, "more than the secret scan reads")


def test_a7_a_line_separator_does_not_hide_a_key(repo: Path) -> None:
    body = f"x = 1 KEY = '{KEY}'\n".encode()
    _commit_refused(repo, {"sep.py": body}, "sep.py:1")


def test_a9_an_anthropic_key_glued_to_a_word_is_found(repo: Path) -> None:
    value = "example_sk-ant-" + "api03-" + "Zx9Yw8Vu7Ts6Rq5Po4Nm3Lk2"
    _commit_refused(repo, {"k.py": f"V = {value}\n".encode()}, "Anthropic key")


def test_a9_a_bare_aws_secret_is_found(repo: Path) -> None:
    value = "wJalrXUtnFEMI" + "/K7MDENG/" + "bPxRfiCY" + "1234567890"
    assert len(value) == 40
    _commit_refused(repo, {"aws.ini": f"{value}\n".encode()}, "AWS-style secret key")


def test_a9_a_commit_id_is_not_an_aws_secret(repo: Path) -> None:
    sha = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "pin.txt").write_text(f"{sha}\n", encoding="utf-8")
    _git(repo, "add", "pin.txt")
    rooted = run_tool(repo, "git_commit", {"message": "pin"}, approve_tier_2=_yes)
    assert rooted.is_ok(), rooted.error


@pytest.mark.parametrize("name", [".env", ".env.local", "server.pem", "tls.key"])
def test_a9_key_and_environment_files_are_refused_at_add(repo: Path, name) -> None:
    (repo / name).write_text("x\n", encoding="utf-8")
    asked: list[str] = []
    rooted = run_tool(
        repo, "git_add", {"paths": [name]}, approve_tier_2=lambda n, a: asked.append(n)
    )
    assert not rooted.is_ok() and "RACT does not stage it" in rooted.error
    assert asked == [] and _git(repo, "diff", "--cached", "--name-only") == ""


def test_a9_a_key_inside_a_named_folder_is_refused_at_add(repo: Path) -> None:
    (repo / "keys").mkdir()
    (repo / "keys" / "id_ed25519").write_text("x\n", encoding="utf-8")
    rooted = run_tool(repo, "git_add", {"paths": ["keys"]}, approve_tier_2=_yes)
    assert not rooted.is_ok() and "keys/id_ed25519" in rooted.error
    assert _git(repo, "diff", "--cached", "--name-only") == ""


def test_a9_a_key_file_staged_by_hand_is_refused_at_commit(repo: Path) -> None:
    _commit_refused(repo, {"deploy/id_rsa": b"x\n"}, "RACT does not commit it")


def test_a9_an_example_environment_file_is_staged(repo: Path) -> None:
    (repo / ".env.example").write_text("PORT=8000\n", encoding="utf-8")
    rooted = run_tool(repo, "git_add", {"paths": [".env.example"]}, approve_tier_2=_yes)
    assert rooted.is_ok(), rooted.error


# ---------------------------------------------------------------- B: config


def _marker_command(marker: Path) -> str:
    return f"sh -c 'touch {marker.as_posix()}'"


def test_b_a_filter_defined_by_the_repository_is_refused(repo: Path) -> None:
    marker = repo.parent / "filter-ran.txt"
    _git(repo, "config", "filter.x.clean", _marker_command(marker))
    _git(repo, "config", "filter.x.smudge", _marker_command(marker))
    (repo / ".gitattributes").write_text("* filter=x\n", encoding="utf-8")
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    for tool, args in (
        ("git_status", {}),
        ("git_diff", {}),
        ("git_add", {"paths": ["a.txt"]}),
        ("git_worktree", {"action": "add", "name": "w1"}),
    ):
        rooted = run_tool(repo, tool, args, approve_tier_2=_yes)
        assert not rooted.is_ok() and "filter x" in rooted.error, (tool, rooted.error)
    assert not marker.exists()


def test_b_a_filter_from_an_included_file_is_refused(repo: Path) -> None:
    marker = repo.parent / "filter-ran.txt"
    (repo / "inc.cfg").write_text(
        f'[filter "y"]\n\tclean = {_marker_command(marker)}\n', encoding="utf-8"
    )
    _git(repo, "config", "include.path", "../inc.cfg")
    rooted = run_tool(repo, "git_status", {})
    assert not rooted.is_ok() and "filter y" in rooted.error
    assert not marker.exists()


def test_b_an_attribute_naming_an_undefined_filter_is_refused(repo: Path) -> None:
    (repo / "sub").mkdir()
    (repo / "sub" / ".gitattributes").write_text("*.txt filter=z\n", encoding="utf-8")
    rooted = run_tool(repo, "git_status", {})
    assert not rooted.is_ok() and "filter=z" in rooted.error
    assert "sub/.gitattributes" in rooted.error


def test_b_an_info_attributes_filter_is_refused(repo: Path) -> None:
    info = repo / ".git" / "info"
    info.mkdir(exist_ok=True)
    (info / "attributes").write_text("[attr]m filter=q\n* m\n", encoding="utf-8")
    rooted = run_tool(repo, "git_status", {})
    assert not rooted.is_ok() and "filter=q" in rooted.error


def test_b_a_filter_the_operator_defines_is_allowed(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text(
        '[filter "trusted"]\n\tclean = cat\n\tsmudge = cat\n', encoding="utf-8"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    (repo / ".gitattributes").write_text("*.bin filter=trusted\n", encoding="utf-8")
    rooted = run_tool(repo, "git_status", {})
    assert rooted.is_ok(), rooted.error


def test_b_no_attributes_file_from_config_and_no_signing() -> None:
    argv = git_argv("status")
    for setting in (
        "core.attributesFile=",
        "commit.gpgSign=false",
        "tag.gpgSign=false",
        "log.showSignature=false",
    ):
        assert setting in argv


def test_b_a_signing_program_in_the_repository_never_runs(repo: Path) -> None:
    marker = repo.parent / "gpg-ran.txt"
    script = repo.parent / "fake-gpg.sh"
    script.write_text(f"#!/bin/sh\ntouch '{marker.as_posix()}'\nexit 1\n")
    script.chmod(0o755)
    _git(repo, "config", "commit.gpgSign", "true")
    _git(repo, "config", "gpg.program", script.as_posix())
    _git(repo, "config", "gpg.format", "openpgp")
    _git(repo, "config", "log.showSignature", "true")
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    rooted = run_tool(repo, "git_commit", {"message": "signed?"}, approve_tier_2=_yes)
    assert rooted.is_ok(), rooted.error
    assert run_tool(repo, "git_log", {}).is_ok()
    assert not marker.exists()
    assert _head_subject(repo) == "signed?"


# ---------------------------------------------------------------- C: where git runs


def test_c5_a_project_inside_a_bigger_repository_is_refused(tmp_path: Path) -> None:
    outer = _init(tmp_path / "outer")
    project = outer / "project"
    project.mkdir()
    (project / "b.txt").write_text("x\n", encoding="utf-8")
    for tool, args in (
        ("git_status", {}),
        ("git_diff", {}),
        ("git_add", {"paths": ["b.txt"]}),
        ("git_commit", {"message": "m"}),
    ):
        rooted = run_tool(project, tool, args, approve_tier_2=_yes)
        assert not rooted.is_ok() and "not a git repository of its own" in rooted.error
    assert _git(outer, "status", "--porcelain") == "?? project/\n"


def test_c5_a_project_with_no_repository_is_refused(tmp_path: Path) -> None:
    project = tmp_path / "plain"
    project.mkdir()
    rooted = run_tool(project, "git_status", {})
    assert not rooted.is_ok() and "not a git repository of its own" in rooted.error


def test_c5_a_core_worktree_elsewhere_is_refused(repo: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _git(repo, "config", "core.worktree", elsewhere.as_posix())
    rooted = run_tool(repo, "git_status", {})
    assert not rooted.is_ok() and "which is not the project" in rooted.error


def _link_folder(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except OSError as exc:
        if os.name != "nt":
            pytest.skip(f"no folder link here: {exc}")
    import _winapi

    _winapi.CreateJunction(str(target), str(link))


@pytest.mark.parametrize("where", [".ract", ".ract/worktrees"])
def test_c6_a_link_on_the_worktree_path_is_refused(
    repo: Path, tmp_path: Path, where: str
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = repo / where
    link.parent.mkdir(parents=True, exist_ok=True)
    _link_folder(link, outside)
    asked: list[str] = []
    rooted = run_tool(
        repo,
        "git_worktree",
        {"action": "add", "name": "w1"},
        approve_tier_2=lambda n, a: asked.append(n) or True,
    )
    assert not rooted.is_ok() and "is a link" in rooted.error
    assert asked == [] and list(outside.iterdir()) == []


def test_c6_a_plain_worktree_is_made(repo: Path) -> None:
    rooted = run_tool(
        repo, "git_worktree", {"action": "add", "name": "w1"}, approve_tier_2=_yes
    )
    assert rooted.is_ok(), rooted.error
    assert (repo / ".ract" / "worktrees" / "w1" / "a.txt").is_file()


def test_c10_the_hooks_folder_is_private_and_never_emptied(
    tmp_path: Path, monkeypatch
) -> None:
    first = git_tools._no_hooks_dir()
    assert first == git_tools._no_hooks_dir()
    assert (
        first.name.startswith("ract-no-git-hooks-")
        and first.name != "ract-no-git-hooks"
    )
    planted = tmp_path / "planted"
    planted.mkdir()
    (planted / "pre-commit").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(git_tools, "_hooks_folder", planted)
    with pytest.raises(ToolRefused, match="RACT did not put there"):
        git_tools._no_hooks_dir()
    assert (planted / "pre-commit").exists()


def test_c10_a_link_in_place_of_the_hooks_folder_is_refused(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "hooks-link"
    _link_folder(link, target)
    monkeypatch.setattr(git_tools, "_hooks_folder", link)
    with pytest.raises(ToolRefused, match="is a link"):
        git_tools._no_hooks_dir()


def test_c11_output_past_the_cap_stops_git(repo: Path) -> None:
    (repo / "big.txt").write_bytes(b"z" * (1024 * 1024))
    _git(repo, "add", "big.txt")
    blob = _git(repo, "rev-parse", ":big.txt").strip()
    done = git_tools._run(repo, git_argv("cat-file", "blob", blob), cap=4096)
    assert done.cut and len(done.stdout) == 4096


def test_c11_a_long_diff_is_marked_truncated(repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(git_tools, "_READ_CAP", 2048)
    real = git_tools._run
    monkeypatch.setattr(
        git_tools,
        "_run",
        lambda root, argv, **kw: real(root, argv, **{"cap": 2048, **kw}),
    )
    (repo / "a.txt").write_text("line\n" * 5000, encoding="utf-8")
    result = run_tool(repo, "git_diff", {}).unwrap()
    assert result.truncated


# ---------------------------------------------------------------- D: what the operator sees


def test_d8_the_question_quotes_the_argv() -> None:
    assert (
        question_lines("git_add", AddArgs(paths=["a b"]))[0]
        != question_lines("git_add", AddArgs(paths=["a", "b"]))[0]
    )
    assert question_lines("git_add", AddArgs(paths=["a b"]))[0] == "git add -- 'a b'"


def test_d8_the_commit_question_shows_the_files_and_the_scan(repo: Path) -> None:
    (repo / "a.txt").write_text("two\nthree\n", encoding="utf-8")
    (repo / "c.txt").write_text("new\n", encoding="utf-8")
    _git(repo, "add", "a.txt", "c.txt")
    seen: list[list[str]] = []
    rooted = run_tool(
        repo,
        "git_commit",
        {"message": "two files"},
        approve_tier_2=lambda n, a: seen.append(question_lines(n, a)) or True,
    )
    assert rooted.is_ok(), rooted.error
    lines = seen[0]
    assert lines[0] == "git commit -m 'two files'"
    assert "it commits 2 staged file(s):" in lines
    assert "  M a.txt (+2 -1)" in lines and "  A c.txt (+1 -0)" in lines
    assert any(line.startswith("secret scan: no secret found") for line in lines)


def test_d8_a_change_staged_after_the_question_is_refused(repo: Path) -> None:
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    _git(repo, "add", "a.txt")

    def stage_more(name, args):
        (repo / "late.txt").write_text("late\n", encoding="utf-8")
        _git(repo, "add", "late.txt")
        return True

    rooted = run_tool(repo, "git_commit", {"message": "m"}, approve_tier_2=stage_more)
    assert not rooted.is_ok() and "not the one the question showed" in rooted.error
    assert _head_subject(repo) == "first"


def test_d8_the_add_question_lists_what_it_stages(repo: Path) -> None:
    (repo / "d").mkdir()
    (repo / "d" / "one.txt").write_text("1\n", encoding="utf-8")
    (repo / "d" / "two.txt").write_text("2\n", encoding="utf-8")
    seen: list[list[str]] = []
    run_tool(
        repo,
        "git_add",
        {"paths": ["d"]},
        approve_tier_2=lambda n, a: seen.append(question_lines(n, a)) and False,
    )
    assert seen[0][1:] == ["it stages 2 file(s):", "  d/one.txt", "  d/two.txt"]


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "send-pack", "x", "main"],
        ["git", "fetch-pack", "x"],
        ["git", "http-push", "x"],
        ["git", "archive", "--remote=x", "HEAD"],
        ["git", "submodule", "update"],
    ],
)
def test_d12_remote_plumbing_always_asks(repo: Path, argv: list[str]) -> None:
    result = classify(argv, None, repo)
    assert result.outcome == "asks" and "remote git" in result.reason, result
