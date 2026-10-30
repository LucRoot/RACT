"""B-111 (ADR-0048 D3): the tier-3 grant holds only when the operator's pinned key signed it.

Throwaway keys in temporary folders only. Every refusal says why.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ract.policy.grant import PolicyInvalid, load_grant, parse_policy, revoke, sign
from ract.policy.operator_key import generate, unlock

PASS = "throwaway passphrase for a test"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def _policy(project: Path, key_id: str, **over: str) -> str:
    fields = {
        "project_root": os.path.realpath(project),
        "issued_at": "2026-10-30T10:00:00Z",
        "expires_at": "2027-01-28T10:00:00Z",
        "argv": "[python, -m, pytest]",
        "max_mode": "ask",
        "sandbox": "best_effort",
    }
    fields.update(over)
    return (
        "version: 1\n"
        "binding:\n"
        f"  project_root: '{fields['project_root']}'\n"
        f"issued_at: {fields['issued_at']}\n"
        f"expires_at: {fields['expires_at']}\n"
        f"key_id: {key_id}\n"
        f"max_mode: {fields['max_mode']}\n"
        f"sandbox: {fields['sandbox']}\n"
        "commands:\n"
        "  allow:\n"
        "    - id: tests\n"
        f"      argv: {fields['argv']}\n"
        "      network: false\n"
        "      timeout_s: 900\n"
        "  deny:\n"
        "    - argv: [git, push]\n"
    )


@pytest.fixture
def setup(tmp_path: Path):
    cfg = tmp_path / "config"
    key = generate(PASS, config=cfg)
    project = tmp_path / "project"
    (project / ".ract").mkdir(parents=True)
    return cfg, key, project


def _write_and_sign(cfg: Path, key, project: Path, **over: str) -> str:
    (project / ".ract" / "policy.yaml").write_text(
        _policy(project, key.key_id, **over), encoding="utf-8"
    )
    return sign(project, unlock(PASS, config=cfg), key)


def test_a_signed_grant_holds(setup) -> None:
    cfg, key, project = setup
    digest = _write_and_sign(cfg, key, project)
    state = load_grant(project, config=cfg, now=NOW)
    assert state.holds and state.digest == digest
    assert state.policy.commands.allow[0].argv == ["python", "-m", "pytest"]
    assert state.policy.sandbox == "best_effort"


def test_no_grant_and_an_unsigned_grant(setup) -> None:
    cfg, key, project = setup
    assert load_grant(project, config=cfg, now=NOW).status == "none"
    (project / ".ract" / "policy.yaml").write_text(
        _policy(project, key.key_id), encoding="utf-8"
    )
    state = load_grant(project, config=cfg, now=NOW)
    assert state.status == "unsigned" and not state.holds


def test_a_cloned_repositorys_grant_grants_nothing(setup, tmp_path: Path) -> None:
    # Someone else signed it with their key; this machine pins another key.
    cfg, _key, project = setup
    theirs = tmp_path / "their-config"
    their_key = generate(PASS, config=theirs)
    (project / ".ract" / "policy.yaml").write_text(
        _policy(project, their_key.key_id), encoding="utf-8"
    )
    sign(project, unlock(PASS, config=theirs), their_key)
    state = load_grant(project, config=cfg, now=NOW)
    assert (
        state.status == "invalid" and "not signed by your operator key" in state.reason
    )


def test_an_edit_after_signing_breaks_the_signature(setup) -> None:
    cfg, key, project = setup
    _write_and_sign(cfg, key, project)
    path = project / ".ract" / "policy.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("[git, push]", "[git, fetch]"),
        encoding="utf-8",
    )
    state = load_grant(project, config=cfg, now=NOW)
    assert state.status == "invalid" and "does not match" in state.reason


def test_a_grant_copied_to_another_folder_is_bound_elsewhere(
    setup, tmp_path: Path
) -> None:
    cfg, key, project = setup
    _write_and_sign(cfg, key, project)
    copy = tmp_path / "copy"
    shutil.copytree(project, copy)
    state = load_grant(copy, config=cfg, now=NOW)
    assert state.status == "invalid" and "another folder" in state.reason


def test_expired_and_not_yet(setup) -> None:
    cfg, key, project = setup
    _write_and_sign(cfg, key, project)
    late = load_grant(project, config=cfg, now=NOW + timedelta(days=120))
    assert late.status == "expired" and late.reason == "grant expired 2027-01-28"
    early = load_grant(project, config=cfg, now=NOW - timedelta(days=2))
    assert early.status == "not-yet"


def test_a_revoked_grant_stays_refused_when_its_files_come_back(
    setup, tmp_path: Path
) -> None:
    cfg, key, project = setup
    _write_and_sign(cfg, key, project)
    saved = tmp_path / "from-git-history"
    shutil.copytree(project / ".ract", saved)
    revoke(project, config=cfg)
    assert not (project / ".ract" / "policy.yaml.sig").exists()
    shutil.copy(saved / "policy.yaml.sig", project / ".ract" / "policy.yaml.sig")
    state = load_grant(project, config=cfg, now=NOW)
    assert state.status == "revoked" and not state.holds


def test_signing_refuses_a_policy_for_another_key_or_folder(
    setup, tmp_path: Path
) -> None:
    cfg, key, project = setup
    (project / ".ract" / "policy.yaml").write_text(
        _policy(project, "ed25519:0000000000000000"), encoding="utf-8"
    )
    with pytest.raises(PolicyInvalid, match="is not your key"):
        sign(project, unlock(PASS, config=cfg), key)
    (project / ".ract" / "policy.yaml").write_text(
        _policy(project, key.key_id, project_root=str(tmp_path / "elsewhere")),
        encoding="utf-8",
    )
    with pytest.raises(PolicyInvalid, match="is not this folder"):
        sign(project, unlock(PASS, config=cfg), key)
    assert not (project / ".ract" / "policy.yaml.sig").exists()


@pytest.mark.parametrize(
    ("over", "expected"),
    [
        (
            {"argv": "[python]"},
            "policy.yaml:12 commands.allow[0].argv: ['python'] is too broad: an interpreter "
            "alone runs any code. hint: name the module or script, for example "
            "[python, -m, pytest]",
        ),
        (
            {"expires_at": "2028-10-30T10:00:00Z"},
            "policy.yaml:5 expires_at: a grant lasts at most 365 days",
        ),
        ({"max_mode": "everything"}, "policy.yaml:7 max_mode:"),
        ({"sandbox": "maybe"}, "policy.yaml:8 sandbox:"),
    ],
)
def test_a_policy_error_names_the_file_line_field_and_fix(
    setup, over: dict[str, str], expected: str
) -> None:
    _cfg, key, project = setup
    with pytest.raises(PolicyInvalid) as caught:
        parse_policy(_policy(project, key.key_id, **over))
    assert any(p.startswith(expected) for p in caught.value.problems), (
        caught.value.problems
    )


def test_an_unknown_field_refuses_the_whole_grant(setup) -> None:
    _cfg, key, project = setup
    text = _policy(project, key.key_id) + "allow_everything: true\n"
    with pytest.raises(PolicyInvalid) as caught:
        parse_policy(text)
    assert any("allow_everything" in p for p in caught.value.problems)
