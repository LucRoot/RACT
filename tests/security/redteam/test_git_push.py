"""B-027 red team: ``git_push`` (slice f). Nothing reaches a remote.

A push needs a grant that holds, a rule for ``git push``, a signed handshake
for that remote and branch, and the operator's yes; without any one of them
nothing runs. The scripted runner stands in for git.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.handshake_registry import HandshakeRegistry
from ract.policy.operator_key import unlock
from ract.tools.git_tools import push_handshake_id
from tests.security.redteam._world import PASS, RULES, build, call, nothing_ran

PUSH_RULE = "    - id: push\n      argv: [git, push]\n"
ARGS = {"remote": "origin", "branch": "main"}


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    return build(tmp_path, monkeypatch)


def _approve_handshake(world, *, signed: bool = True) -> None:
    registry = HandshakeRegistry(world.project)
    hid = push_handshake_id("origin", "main")
    registry.add(hid, "push main to origin", "the operator approves")
    signer = (world.key.key_id, unlock(PASS)) if signed else None
    registry.update_status(hid, "approved", signer=signer)


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
