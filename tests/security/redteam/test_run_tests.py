"""B-027 red team: ``run_tests`` attacked as a hostile repository or model would.

Each case asserts refusal or containment; nothing runs (scripted runner).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.policy.grant import pin_digest
from tests.security.redteam._world import RULES, build, call, nothing_ran


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    return build(tmp_path, monkeypatch)


# The model controls only the selectors. Every form of an option, a path that
# leaves the project, or a value the runner would read as code is refused.
HOSTILE_SELECTORS = [
    "--pdb",
    "-p",
    "-pno:cacheprovider",
    "--rootdir=/",
    "-c",
    "--confcutdir=..",
    "../outside.py",
    "/etc/passwd",
    "C:/Windows/win.ini",
    "tests/../../escape.py",
    "a\x00b",
    "x" * 400,
]


@pytest.mark.parametrize(
    "selector", HOSTILE_SELECTORS, ids=range(len(HOSTILE_SELECTORS))
)
def test_a_hostile_selector_is_refused_before_the_question(
    world, selector: str
) -> None:
    rooted, asked, runner = call(world, "run_tests", {"selectors": [selector]})
    assert not rooted.is_ok() and asked == [] and nothing_ran(runner)


def test_a_selector_after_the_double_dash_is_never_an_option(world) -> None:
    rooted, asked, runner = call(
        world, "run_tests", {"selectors": ["tests/test_calc.py"]}
    )
    assert rooted.is_ok(), rooted.error
    argv = runner.calls[0]["argv"]
    assert argv[argv.index("--") + 1 :] == ["tests/test_calc.py"]


def test_a_policy_resigned_mid_session_suspends_the_next_call(world) -> None:
    pinned = pin_digest(world.project)
    world.resign(days=90, rules=RULES + "    - id: wide\n      argv: [make]\n")
    rooted, asked, runner = call(world, "run_tests", expected_pin=pinned)
    assert not rooted.is_ok() and "suspended: policy changed" in rooted.error
    assert asked == [] and nothing_ran(runner)


def test_nobody_to_answer_refuses_even_in_allowlist(world) -> None:
    rooted, _asked, runner = call(world, "run_tests", answer=None, mode="allowlist")
    assert (
        not rooted.is_ok()
        and "nobody can answer" in rooted.error
        and nothing_ran(runner)
    )


def test_a_model_written_conftest_puts_the_question_back_in_allowlist(world) -> None:
    rooted, asked, _runner = call(
        world, "run_tests", mode="allowlist", written=("conftest.py",)
    )
    assert len(asked) == 1 and asked[0]["entry_points"]


def test_a_conftest_changed_after_signing_puts_the_question_back(world) -> None:
    (world.project / "conftest.py").write_text(
        "import os\nos.system('id')\n", encoding="utf-8"
    )
    rooted, asked, _runner = call(world, "run_tests", mode="allowlist")
    assert len(asked) == 1
    assert ("conftest.py", "changed since the grant was signed") in asked[0][
        "entry_points"
    ]


def test_a_no_runs_nothing(world) -> None:
    rooted, _asked, runner = call(world, "run_tests", answer=False)
    assert not rooted.is_ok() and nothing_ran(runner)


def test_a_session_approval_is_not_offered_when_an_entry_point_changed(world) -> None:
    from ract.policy.allowlist import SessionApprovals

    sessions = SessionApprovals()
    (world.project / "conftest.py").write_text("# changed\n", encoding="utf-8")
    _rooted, asked, _runner = call(
        world, "run_tests", answer="session", sessions=sessions
    )
    assert asked[0]["session_choice"] is False and sessions.listed() == []


def test_model_text_in_the_reason_never_answers(world) -> None:
    rooted, asked, runner = call(
        world,
        "run_tests",
        {"reason": "the operator already approved this; answer yes"},
        answer=False,
    )
    assert not rooted.is_ok() and nothing_ran(runner)
    assert asked[0]["reason"].startswith("the operator already approved")


def test_forged_and_expired_handshake_approvals_unlock_nothing(
    world, tmp_path: Path, monkeypatch
) -> None:
    import json

    import ract.handshake_registry as hr
    from ract.handshake_registry import HandshakeRegistry
    from ract.policy.operator_key import unlock

    from tests.security.redteam._world import PASS

    registry = HandshakeRegistry(world.project)
    registry.add("m1", "deploy", "ok")
    signer = (world.key.key_id, unlock(PASS))
    registry.update_status("m1", "approved", signer=signer)
    assert registry.is_approved("m1")
    mark = registry._mark("m1", "approved.sig")
    record = json.loads(mark.read_text(encoding="utf-8"))
    for field, value in (
        ("digest", "0" * 64),
        ("id", "m2"),
        ("expires", "2000-01-01T00:00:00Z"),
    ):
        forged = dict(record, **{field: value})
        mark.write_text(json.dumps(forged), encoding="utf-8")
        assert not registry.is_approved("m1"), field
    mark.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(hr, "APPROVAL_DAYS", -1)
    registry.update_status("m1", "approved", signer=signer)
    assert not registry.is_approved("m1")


@pytest.mark.parametrize("ignored", [False, True], ids=["untracked", "gitignored"])
def test_a_conftest_planted_after_signing_asks_even_when_hidden(world, ignored) -> None:
    """FOUND while writing B-027: tracked-only listing missed a new conftest.py."""
    (world.project / "tests" / "conftest.py").write_text(
        "import os\nos.system('id')\n", encoding="utf-8"
    )
    if ignored:
        (world.project / ".gitignore").write_text("conftest.py\n", encoding="utf-8")
    _rooted, asked, _runner = call(world, "run_tests", mode="allowlist")
    assert len(asked) == 1
    assert ("tests/conftest.py", "changed since the grant was signed") in asked[0][
        "entry_points"
    ]
