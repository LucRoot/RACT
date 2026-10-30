"""B-111: the session's status line says what the project's grant allows (ADR-0048 D3)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ract.policy.grant import sign
from ract.policy.operator_key import generate, unlock
from ract.session_events import EventStream
from ract.session_render import PlainRenderer
from tests.test_repl import _session

PASS = "throwaway passphrase for a test"


@pytest.fixture
def user_config(tmp_path: Path, monkeypatch) -> Path:
    folder = tmp_path / "user-config"
    monkeypatch.setenv("APPDATA", str(folder))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(folder))
    return folder / "ract"


def _grant(
    project: Path, cfg: Path | None, *, days: int = 90, signer_cfg: Path | None = None
) -> None:
    key = generate(PASS, config=signer_cfg or cfg)
    issued = datetime.now(timezone.utc) - timedelta(hours=1)
    (project / ".ract").mkdir(parents=True, exist_ok=True)
    (project / ".ract" / "policy.yaml").write_text(
        "version: 1\n"
        f"binding:\n  project_root: '{os.path.realpath(project)}'\n"
        f"issued_at: {issued:%Y-%m-%dT%H:%M:%SZ}\n"
        f"expires_at: {issued + timedelta(days=days):%Y-%m-%dT%H:%M:%SZ}\n"
        f"key_id: {key.key_id}\n"
        "max_mode: allowlist\n"
        "sandbox: best_effort\n",
        encoding="utf-8",
    )
    sign(project, unlock(PASS, config=signer_cfg or cfg), key)


def _facts(project: Path) -> tuple[dict, list[str], str]:
    session, _, _console = _session(config=project / "ract.yaml")
    facts = session._tier3_facts()
    out: list[str] = []
    stream = EventStream(session="s")
    stream.subscribe(PlainRenderer(out.append))
    stream.emit(
        "session.started", {"model": "m", "provider": "p", "mode": "default", **facts}
    )
    return facts, list(session._tier3_notes), "".join(out)


def test_no_grant_says_so(tmp_path: Path, user_config: Path) -> None:
    facts, notes, text = _facts(tmp_path)
    assert facts == {"tier3": "off", "tier3_status": "T3 off (no grant)"}
    assert notes == [] and "T3 off (no grant)" in text


def test_a_signed_grant_opens_ask(tmp_path: Path, user_config: Path) -> None:
    _grant(tmp_path, user_config)
    facts, notes, text = _facts(tmp_path)
    # Ask, not the grant's max_mode: the session raises it only on request.
    assert facts == {"tier3": "ask", "tier3_status": "T3 ask"}
    assert notes == [] and "| T3 ask" in text


def test_a_cloned_repositorys_grant_is_off_and_says_why(
    tmp_path: Path, user_config: Path
) -> None:
    generate(PASS, config=user_config)  # this machine's own key is pinned
    _grant(tmp_path / "repo", None, signer_cfg=tmp_path / "their-config")
    facts, notes, _text = _facts(tmp_path / "repo")
    assert facts["tier3"] == "off"
    assert notes == ["tier 3 is off: the grant is not signed by your operator key"]


def test_a_grant_expiring_this_week_adds_a_notice(
    tmp_path: Path, user_config: Path
) -> None:
    _grant(tmp_path, user_config, days=3)
    facts, notes, _text = _facts(tmp_path)
    assert facts["tier3"] == "ask"
    assert len(notes) == 1 and "expires in" in notes[0] and "sign it again" in notes[0]


def test_permissions_says_why_a_grant_does_not_hold(
    tmp_path: Path, user_config: Path
) -> None:
    from ract.policy.cli import permission_lines

    generate(PASS, config=user_config)
    _grant(tmp_path / "repo", None, signer_cfg=tmp_path / "their-config")
    first = permission_lines(tmp_path / "repo")[0]
    assert first == "Tier 3: off: the grant is not signed by your operator key"


def test_a_policy_change_during_the_session_suspends_tier_3(
    tmp_path: Path, user_config: Path
) -> None:
    _grant(tmp_path, user_config)
    session, _, console = _session(config=tmp_path / "ract.yaml")
    assert session._tier3_facts()["tier3"] == "ask"
    session._check_grant_pin()
    assert session._tier3 == "ask"  # nothing changed: nothing happens

    policy = tmp_path / ".ract" / "policy.yaml"
    policy.write_text(
        policy.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8"
    )
    session._check_grant_pin()
    assert session._tier3 == "suspended"
    assert "T3 suspended: policy changed" in console.text

    # The operator confirms at the terminal; the edited grant no longer holds.
    session.handle("/permissions resume")
    assert session._tier3 == "off"
    assert "Tier 3 now: T3 off (no grant)" in console.text
    assert "the signature does not match policy.yaml" in console.text


def test_a_removed_signature_also_suspends(tmp_path: Path, user_config: Path) -> None:
    _grant(tmp_path, user_config)
    session, _, _console = _session(config=tmp_path / "ract.yaml")
    session._tier3_facts()
    (tmp_path / ".ract" / "policy.yaml.sig").unlink()
    session._check_grant_pin()
    assert session._tier3 == "suspended"
