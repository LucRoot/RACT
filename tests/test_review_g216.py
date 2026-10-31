"""G-216 (the MANAGER's senior review, part 4): W1 to W6.

No test runs a command: tier-3 calls go to the scripted runner or a
stand-in that executes nothing. Keys are throwaways in temporary folders.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ract.handshake_registry import HandshakeRegistry
from ract.policy import tier3
from ract.policy.grant import pin_digest, sign
from ract.policy.operator_key import generate, unlock
from ract.session_events import EventStream, SessionEvent
from ract.session_turn import TurnRequest, run_turn
from ract.tools import run_tool
from ract.tools.command import ScriptedRunner
from tests.test_j4_named_test_runs import INTENT, StandIn, ws  # noqa: F401 (fixture)

PASS = "throwaway passphrase for a test"


class Grant:
    """One throwaway key and a grant that can be re-signed with other terms."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.key = generate(PASS)
        self.write(days=30)

    def write(
        self,
        *,
        days: int,
        rules: str = "    - id: tests\n      argv: [python, -m, pytest]\n",
    ) -> str:
        now = datetime.now(timezone.utc) - timedelta(hours=1)
        (self.root / ".ract").mkdir(exist_ok=True)
        (self.root / ".ract" / "policy.yaml").write_text(
            "version: 1\n"
            f"binding:\n  project_root: '{os.path.realpath(self.root)}'\n"
            f"issued_at: {now:%Y-%m-%dT%H:%M:%SZ}\n"
            f"expires_at: {now + timedelta(days=days):%Y-%m-%dT%H:%M:%SZ}\n"
            f"key_id: {self.key.key_id}\n"
            "sandbox: best_effort\n"
            f"commands:\n  allow:\n{rules}",
            encoding="utf-8",
        )
        sign(self.root, unlock(PASS), self.key)
        return pin_digest(self.root)


@pytest.fixture
def project(tmp_path: Path, monkeypatch) -> Path:
    cfg = tmp_path / "user-config"
    monkeypatch.setenv("APPDATA", str(cfg))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    root = tmp_path / "calc"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_calc.py").write_text(
        "def test_add():\n    pass\n", encoding="utf-8"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / ("python.exe" if os.name == "nt" else "python")
    exe.write_text("", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    return root


def _call(ctx: tier3.Tier3Context):
    with tier3.bound(ctx):
        return run_tool(ctx.project, "run_tests", {"selectors": ["tests/test_calc.py"]})


# ---------------------------------------------------------------- W1


def test_w1_a_grant_resigned_during_a_step_refuses_the_next_call(project: Path) -> None:
    grant = Grant(project)
    runner = ScriptedRunner([{}])
    ctx = tier3.for_project(project, approve=lambda facts: True, runner=runner)
    assert _call(ctx).is_ok()  # the pinned grant runs
    grant.write(days=60)  # re-signed, validly, during the step
    rooted = _call(ctx)
    assert not rooted.is_ok() and "suspended: policy changed" in rooted.error
    assert "/permissions resume" in rooted.error + rooted.hint
    assert len(runner.calls) == 1  # nothing ran after the change
    assert _call(ctx).error == rooted.error  # it stays suspended


def test_w1_the_sessions_pin_suspends_a_new_steps_context(project: Path) -> None:
    grant = Grant(project)
    session_pin = pin_digest(project)
    grant.write(days=60)
    runner = ScriptedRunner([{}])
    ctx = tier3.for_project(
        project, lambda facts: True, runner, expected_pin=session_pin
    )
    assert ctx.grant.status == "suspended"
    rooted = _call(ctx)
    assert not rooted.is_ok() and "/permissions resume" in rooted.error
    assert runner.calls == []
    # After the operator confirms, the session's pin is the new one and it asks.
    asked: list[dict] = []
    ctx = tier3.for_project(
        project,
        lambda facts: asked.append(facts) or True,
        runner,
        expected_pin=pin_digest(project),
    )
    assert _call(ctx).is_ok() and len(asked) == 1


def test_w1_a_change_while_the_question_is_open_runs_nothing(project: Path) -> None:
    grant = Grant(project)
    runner = ScriptedRunner([{}])

    def approve(facts: dict) -> bool:
        grant.write(
            days=60,
            rules="    - id: tests\n      argv: [python, -m, pytest]\n    - id: all\n      argv: [make, test]\n",
        )
        return True

    rooted = _call(tier3.for_project(project, approve, runner))
    assert not rooted.is_ok() and "nothing ran" in rooted.error and runner.calls == []


def _turn(
    project: Path,
    monkeypatch,
    runner,
    *,
    auto: bool,
    terminal: bool,
    pin: str | None = None,
):
    monkeypatch.setattr("ract.tools.command.default_runner", lambda rule=None: runner)
    asked: list[str] = []

    def read_line(prompt: str) -> str:
        asked.append(prompt)
        return "y"

    monkeypatch.setattr("ract.approval_callback.read_line", read_line)
    events: list[SessionEvent] = []
    stream = EventStream(session="s-g216")
    stream.subscribe(events.append)
    request = TurnRequest(
        config=project / "ract.yaml",
        intent=INTENT,
        session_id="s-g216",
        resume=False,
        auto=auto,
        terminal=terminal,
        grant_pin=pin,
    )
    code = run_turn(stream, request, turn=1, cancel=threading.Event())
    return code, events[-1].data["verification"], asked


def test_w1_a_turn_under_a_stale_session_pin_runs_no_test(
    ws: Path,  # noqa: F811
    monkeypatch,
) -> None:
    grant = Grant(ws)
    stale = pin_digest(ws)
    grant.write(days=60)
    runner = StandIn(0)
    code, verification, _ = _turn(
        ws, monkeypatch, runner, auto=True, terminal=True, pin=stale
    )
    assert code == 0 and runner.calls == []
    assert "suspended: policy changed" in verification["not_run_reason"]
    assert "/permissions resume" in verification["not_run_reason"]


# ---------------------------------------------------------------- W4


@pytest.mark.parametrize(
    "auto, terminal, runs",
    [
        (True, True, True),  # the default REPL: steps are asked about at a terminal
        (True, False, True),  # ract run --auto: someone answers each step
        (False, True, True),  # REPL auto-accept: edits are accepted, tier 3 still asks
        (False, False, False),  # --yolo and headless (ract -p): nobody to ask
    ],
    ids=["default-repl", "run-auto", "repl-auto-accept", "yolo-or-headless"],
)
def test_w4_who_answers_the_named_test(
    ws: Path,  # noqa: F811
    monkeypatch,
    auto,
    terminal,
    runs,
) -> None:
    Grant(ws)
    runner = StandIn(0)
    code, verification, asked = _turn(
        ws, monkeypatch, runner, auto=auto, terminal=terminal
    )
    assert code == 0
    if runs:
        assert runner.calls and "Run it once? [y/N]: " in asked
        assert verification["status"] == "verified"
    else:
        assert runner.calls == [] and "Run it once? [y/N]: " not in asked
        assert (
            verification["not_run_reason"]
            == "nobody can answer the tier-3 question here"
        )


# ---------------------------------------------------------------- W6


def _repl(project: Path, typed: list[str]):
    from tests.test_repl import _session

    session, _calls, console = _session(typed, config=project / "ract.yaml")
    session._tier3_facts()
    return session, console


def test_w6_resume_shows_what_changed_and_without_y_changes_nothing(
    project: Path,
) -> None:
    grant = Grant(project)
    session, console = _repl(project, ["n"])
    pinned = session._grant_pin
    grant.write(
        days=60,
        rules="    - id: tests\n      argv: [python, -m, pytest]\n    - id: all\n      argv: [make, test]\n",
    )
    session._cmd_permissions(["resume"])
    text = console.text
    assert "allow rule added: make test" in text and "expiry:" in text
    assert "Nothing changed" in text and session._grant_pin == pinned


def test_w6_resume_with_y_pins_the_new_grant(project: Path) -> None:
    grant = Grant(project)
    session, console = _repl(project, ["y"])
    new = grant.write(days=60)
    session._cmd_permissions(["resume"])
    assert session._grant_pin == new and "Tier 3 now: T3 ask" in console.text


def test_w6_resume_at_eof_changes_nothing(project: Path) -> None:
    grant = Grant(project)
    session, console = _repl(project, [])
    pinned = session._grant_pin
    grant.write(days=60)
    session._cmd_permissions(["resume"])
    assert session._grant_pin == pinned and "Nothing changed" in console.text


# ---------------------------------------------------------------- W2


def _link(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"this machine cannot make a link: {exc}")


def _folder_link(target: Path, link: Path) -> None:
    """A link to a folder: a junction on Windows (no privilege needed), else a symlink."""
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def test_w2_migrate_skips_a_planted_folder_link(tmp_path: Path) -> None:
    from ract.key_paths import migrate, repo_key_dir

    root = tmp_path / "repo"
    archive = root / ".ract" / "sandbox" / "archive"
    archive.mkdir(parents=True)
    (archive / "a.key").write_text("ours", encoding="utf-8")
    elsewhere = tmp_path / "someone-elses-keys"
    elsewhere.mkdir()
    (elsewhere / "theirs.key").write_text("theirs", encoding="utf-8")
    _folder_link(elsewhere, root / ".ract" / "sandbox" / "linked")
    alm_elsewhere = tmp_path / "more-keys"
    alm_elsewhere.mkdir()
    (alm_elsewhere / "x.key").write_text("x", encoding="utf-8")
    _folder_link(alm_elsewhere, root / ".ract" / "alm")
    lines = migrate(root)
    assert (elsewhere / "theirs.key").read_text(encoding="utf-8") == "theirs"
    assert (alm_elsewhere / "x.key").read_text(encoding="utf-8") == "x"
    assert (repo_key_dir(root, "sandbox") / "archive" / "a.key").is_file()
    skipped = [line for line in lines if line.startswith("skipped")]
    assert len(skipped) == 2 and all("it is a link" in line for line in skipped)


def test_w3_a_key_under_a_folder_link_is_never_read(tmp_path: Path, capsys) -> None:
    from ract.security.keys import SandboxKey

    root = tmp_path / "repo"
    (root / ".ract" / "sandbox").mkdir(parents=True)
    planted = tmp_path / "planted"
    planted.mkdir()
    run_id = bytes.fromhex("12" * 8)
    (planted / f"{run_id.hex()}.key").write_bytes(_pem())
    _folder_link(planted, root / ".ract" / "sandbox" / "archive")
    assert SandboxKey.load_archived(run_id, root) is None
    assert "it is a link" in capsys.readouterr().err


def test_w2_migrate_skips_planted_links(tmp_path: Path) -> None:
    from ract.key_paths import migrate, repo_key_dir

    root = tmp_path / "repo"
    archive = root / ".ract" / "sandbox" / "archive"
    archive.mkdir(parents=True)
    (archive / "a.key").write_text("ours", encoding="utf-8")
    elsewhere = tmp_path / "someone-elses-keys"
    elsewhere.mkdir()
    (elsewhere / "theirs.key").write_text("theirs", encoding="utf-8")
    (tmp_path / "lone.key").write_text("lone", encoding="utf-8")
    _link(elsewhere, root / ".ract" / "sandbox" / "linked")
    _link(tmp_path / "lone.key", archive / "b.key")
    _link(tmp_path / "lone.key", root / ".ract" / "operator.key")
    lines = migrate(root)
    assert (elsewhere / "theirs.key").read_text(encoding="utf-8") == "theirs"
    assert (tmp_path / "lone.key").read_text(encoding="utf-8") == "lone"
    assert (repo_key_dir(root, "sandbox") / "archive" / "a.key").is_file()
    skipped = [line for line in lines if line.startswith("skipped")]
    assert len(skipped) == 3 and all("it is a link" in line for line in skipped)


# ---------------------------------------------------------------- W3


def _pem() -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
@pytest.mark.parametrize("kind", ["sandbox", "alm"])
def test_w3_a_key_the_repository_tracks_is_never_read(
    tmp_path: Path, kind: str, capsys
) -> None:
    from ract.security.alm_verifier_key import AlmVerifierKey
    from ract.security.keys import SandboxKey

    loader = SandboxKey if kind == "sandbox" else AlmVerifierKey
    root = tmp_path / "repo"
    archive = root / ".ract" / kind / "archive"
    archive.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    run_id = bytes.fromhex("ab" * 8)
    (archive / f"{run_id.hex()}.key").write_bytes(_pem())
    subprocess.run(["git", "add", "-f", "."], cwd=root, check=True)
    assert loader.load_archived(run_id, root) is None
    assert "the repository tracks it" in capsys.readouterr().err


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_w3_an_untracked_old_key_is_read_with_a_warning_every_time(
    tmp_path: Path, capsys
) -> None:
    from ract.security.keys import SandboxKey

    root = tmp_path / "repo"
    archive = root / ".ract" / "sandbox" / "archive"
    archive.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    run_id = bytes.fromhex("cd" * 8)
    (archive / f"{run_id.hex()}.key").write_bytes(_pem())
    for _ in range(2):
        assert SandboxKey.load_archived(run_id, root) is not None
    assert capsys.readouterr().err.count("migrate-keys") == 2


def test_w3_a_linked_old_key_is_never_read(tmp_path: Path) -> None:
    from ract.security.keys import SandboxKey

    root = tmp_path / "repo"
    archive = root / ".ract" / "sandbox" / "archive"
    archive.mkdir(parents=True)
    run_id = bytes.fromhex("ef" * 8)
    (tmp_path / "planted.key").write_bytes(_pem())
    _link(tmp_path / "planted.key", archive / f"{run_id.hex()}.key")
    assert SandboxKey.load_archived(run_id, root) is None


# ---------------------------------------------------------------- W5


def test_w5_an_unsigned_approval_says_what_to_do(tmp_path: Path) -> None:
    registry = HandshakeRegistry(tmp_path)
    registry.add("m1", "deploy", "ok")
    registry.update_status("m1", "approved")
    assert registry.blocks_commit(["m1"]) == ["m1"]
    assert registry.unsigned_reason("m1") == (
        "m1 was approved without the operator's signature; "
        "`ract policy init --guided` creates the key, then approve again"
    )
    registry.add("m2", "other", "ok")
    assert registry.unsigned_reason("m2") is None  # pending: the usual wording
