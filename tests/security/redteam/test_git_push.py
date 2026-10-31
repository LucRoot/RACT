"""B-027 red team: ``git_push`` (slice f). Nothing reaches a remote.

A push needs a grant that holds, a rule for ``git push``, a repository
config that sets no transport or credential program, a signed handshake for
the resolved push URL, the branch and its commit, and the operator's yes;
without any one of them nothing runs. The scripted runner stands in for
git, and the remote is a local bare repository.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ract.handshake_registry import HandshakeRegistry
from ract.policy.operator_key import unlock
from ract.tools.git_tools import push_handshake_id, push_target
from tests.security.redteam._world import PASS, RULES, build, call, nothing_ran

PUSH_RULE = "    - id: push\n      argv: [git, push]\n"
ARGS = {"remote": "origin", "branch": "main"}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    world = build(tmp_path, monkeypatch)
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True
    )
    _git(world.project, "remote", "add", "origin", bare.as_posix())
    _git(world.project, "update-ref", "refs/heads/main", "HEAD")
    return world


def _hid(world) -> str:
    url, head = push_target(world.project, "origin", "main")
    return push_handshake_id(url, "main", head)


def _approve_handshake(world, *, signed: bool = True) -> str:
    registry = HandshakeRegistry(world.project)
    hid = _hid(world)
    registry.add(hid, "push main to origin", "the operator approves")
    signer = (world.key.key_id, unlock(PASS)) if signed else None
    registry.update_status(hid, "approved", signer=signer)
    return hid


def test_no_rule_no_push(world) -> None:
    _approve_handshake(world)
    rooted, asked, runner = call(world, "git_push", ARGS)
    assert not rooted.is_ok() and "no rule for git push" in rooted.error
    assert asked == [] and nothing_ran(runner)


def test_no_handshake_no_push(world) -> None:
    world.resign(rules=RULES + PUSH_RULE)
    rooted, asked, runner = call(world, "git_push", ARGS)
    assert not rooted.is_ok() and "handshake" in rooted.error
    assert asked == [] and nothing_ran(runner)


def test_an_unsigned_handshake_approval_is_no_handshake(world) -> None:
    world.resign(rules=RULES + PUSH_RULE)
    _approve_handshake(world, signed=False)
    rooted, _asked, runner = call(world, "git_push", ARGS)
    assert not rooted.is_ok() and nothing_ran(runner)


def test_remote_git_asks_even_in_allowlist_and_a_no_runs_nothing(world) -> None:
    world.resign(rules=RULES + PUSH_RULE)
    _approve_handshake(world)
    rooted, asked, runner = call(
        world, "git_push", ARGS, mode="allowlist", answer=False
    )
    assert len(asked) == 1 and not rooted.is_ok() and nothing_ran(runner)


def test_nobody_to_answer_never_pushes(world) -> None:
    world.resign(rules=RULES + PUSH_RULE)
    _approve_handshake(world)
    rooted, _asked, runner = call(world, "git_push", ARGS, answer=None)
    assert not rooted.is_ok() and nothing_ran(runner)


@pytest.mark.parametrize(
    "args",
    [
        {"remote": "-f", "branch": "main"},
        {"remote": "origin", "branch": "--force"},
        {"remote": "origin", "branch": "main:refs/heads/x"},
    ],
)
def test_options_and_refspecs_are_refused(world, args) -> None:
    world.resign(rules=RULES + PUSH_RULE)
    rooted, asked, runner = call(world, "git_push", args)
    assert not rooted.is_ok() and asked == [] and nothing_ran(runner)


def test_with_everything_it_asks_then_runs_once(world) -> None:
    world.resign(rules=RULES + PUSH_RULE)
    _approve_handshake(world)
    rooted, asked, runner = call(world, "git_push", ARGS)
    assert rooted.is_ok(), rooted.error
    assert len(asked) == 1
    assert runner.calls[0]["argv"][-3:] == ["push", "origin", "main"]


def test_the_push_runs_with_d8_hardening(world) -> None:
    """Review finding 7: no repository hook or fsmonitor runs during a push."""
    world.resign(rules=RULES + PUSH_RULE)
    _approve_handshake(world)
    rooted, _asked, runner = call(world, "git_push", ARGS)
    argv = runner.calls[0]["argv"]
    assert "core.fsmonitor=false" in argv
    assert any(a.startswith("core.hooksPath=") for a in argv)
    assert "protocol.ext.allow=never" in argv


# ---------------------------------------------------------------- G-239 B-push


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("core.sshCommand", "sh -c 'touch ran'"),
        ("core.gitProxy", "evil-proxy"),
        ("credential.helper", "!sh -c 'touch ran'"),
        ("credential.https://example.invalid.helper", "evil"),
        ("remote.origin.receivepack", "sh -c 'touch ran'"),
        ("remote.origin.uploadpack", "sh -c 'touch ran'"),
        ("remote.origin.proxy", "http://proxy.invalid"),
        ("remote.origin.pushurl", "file:///elsewhere.git"),
        ("url.file:///elsewhere/.insteadOf", "file:///"),
        ("url.file:///elsewhere/.pushInsteadOf", "file:///"),
        ("http.proxy", "http://proxy.invalid"),
        ("protocol.ext.allow", "always"),
    ],
)
def test_a_hostile_repository_config_refuses_the_push(world, key, value) -> None:
    world.resign(rules=RULES + PUSH_RULE)
    _approve_handshake(world)
    _git(world.project, "config", key, value)
    rooted, asked, runner = call(world, "git_push", ARGS)
    assert not rooted.is_ok() and "repository's own config sets" in rooted.error
    assert asked == [] and nothing_ran(runner)


def test_a_hostile_key_in_an_included_file_refuses_the_push(world) -> None:
    world.resign(rules=RULES + PUSH_RULE)
    _approve_handshake(world)
    (world.project / "inc.cfg").write_text(
        "[core]\n\tsshCommand = sh -c 'touch ran'\n", encoding="utf-8"
    )
    _git(world.project, "config", "include.path", "../inc.cfg")
    rooted, asked, runner = call(world, "git_push", ARGS)
    assert not rooted.is_ok() and "core.sshcommand" in rooted.error
    assert asked == [] and nothing_ran(runner)


def test_an_approval_does_not_cover_a_later_commit(world) -> None:
    world.resign(rules=RULES + PUSH_RULE)
    approved = _approve_handshake(world)
    _git(world.project, "commit", "-q", "--allow-empty", "-m", "later")
    _git(world.project, "update-ref", "refs/heads/main", "HEAD")
    rooted, asked, runner = call(world, "git_push", ARGS)
    assert not rooted.is_ok() and "handshake" in rooted.error
    assert approved not in rooted.error and asked == [] and nothing_ran(runner)


def test_an_approval_does_not_cover_another_url(world, tmp_path: Path) -> None:
    world.resign(rules=RULES + PUSH_RULE)
    _approve_handshake(world)
    other = tmp_path / "other.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(other)], check=True, capture_output=True
    )
    _git(world.project, "remote", "set-url", "origin", other.as_posix())
    rooted, asked, runner = call(world, "git_push", ARGS)
    assert not rooted.is_ok() and other.as_posix() in rooted.error
    assert asked == [] and nothing_ran(runner)


def test_the_question_shows_the_resolved_url_and_commit(world) -> None:
    world.resign(rules=RULES + PUSH_RULE)
    hid = _approve_handshake(world)
    url, head = push_target(world.project, "origin", "main")
    assert hid == f"git-push:{url}:main:{head}" and url.endswith("remote.git")
    rooted, asked, _runner = call(world, "git_push", ARGS)
    assert rooted.is_ok(), rooted.error
    shown = str(asked[0])
    assert f"the push URL is {url}" in shown and head in shown


def test_credentials_in_the_push_url_are_not_shown(world) -> None:
    _git(
        world.project,
        "remote",
        "set-url",
        "origin",
        "https://deploy:" + "s3cr3t-pass-word" + "@example.invalid/r.git",
    )
    url, _head = push_target(world.project, "origin", "main")
    assert "s3cr3t-pass-word" not in url
