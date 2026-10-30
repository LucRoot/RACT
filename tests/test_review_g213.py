"""G-213 (the MANAGER's senior review of B-111): K1 to K4, G1, G3, U1, each with its test.

Throwaway keys in temporary folders only.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import ract.policy.operator_key as ok
from ract.policy.grant import load_grant, pin_digest, revoke, sign
from ract.policy.operator_key import OperatorKeyError, WrongPassphrase, generate, unlock

PASS = "throwaway passphrase for a test"


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    return tmp_path / "config" / "ract"


def _file(cfg: Path) -> Path:
    return cfg / "operator" / "operator.key.json"


def test_k1_the_key_file_is_created_owner_only_and_exclusive(
    cfg: Path, monkeypatch
) -> None:
    seen: list[tuple[int, int]] = []
    real_open = os.open

    def recording_open(path, flags, mode=0o777, *a, **k):
        if str(path).endswith(".tmp"):
            seen.append((flags, mode))
        return real_open(path, flags, mode, *a, **k)

    monkeypatch.setattr(ok.os, "open", recording_open)
    generate(PASS, config=cfg)
    assert seen, "the key file was not created through os.open"
    flags, mode = seen[0]
    assert flags & os.O_EXCL and flags & os.O_CREAT and mode == 0o600


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.__setitem__("created_at", "2020-01-01T00:00:00Z"),
        lambda d: d["cipher"].__setitem__("nonce", d["cipher"]["nonce"][::-1]),
        # Another valid 16-byte salt (a malformed one is a different error).
        lambda d: d["kdf"].__setitem__("salt", "AAAAAAAAAAAAAAAAAAAAAA=="),
        lambda d: d["kdf"].__setitem__("n", 2**16),
    ],
)
def test_k2_every_header_field_is_authenticated(cfg: Path, change) -> None:
    generate(PASS, config=cfg)
    data = json.loads(_file(cfg).read_text(encoding="utf-8"))
    change(data)
    _file(cfg).write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(WrongPassphrase) as caught:
        unlock(PASS, config=cfg)
    assert "does not open" in str(caught.value)  # one message, whichever field


@pytest.mark.parametrize(
    ("n", "r", "allowed"), [(2**20, 4, True), (2**20, 5, False), (2**19, 9, False)]
)
def test_k3_scrypt_memory_is_bounded_at_load(
    cfg: Path, n: int, r: int, allowed: bool
) -> None:
    generate(PASS, config=cfg)
    data = json.loads(_file(cfg).read_text(encoding="utf-8"))
    data["kdf"]["n"], data["kdf"]["r"] = n, r
    _file(cfg).write_text(json.dumps(data), encoding="utf-8")
    if allowed:
        # Within the bound the parameters are accepted; the changed header then
        # fails to open with the one message (K2), not as a refused file.
        with pytest.raises(WrongPassphrase):
            unlock(PASS, config=cfg)
    else:
        with pytest.raises(OperatorKeyError, match="does not accept"):
            unlock(PASS, config=cfg)


def test_k4_composed_and_decomposed_passphrases_open_the_same_file(cfg: Path) -> None:
    composed = "café throwaway passphrase"
    decomposed = "café throwaway passphrase"
    assert composed != decomposed
    generate(composed, config=cfg)
    assert unlock(decomposed, config=cfg) is not None


def _signed_project(tmp_path: Path, cfg: Path) -> Path:
    key = generate(PASS, config=cfg)
    project = tmp_path / "project"
    (project / ".ract").mkdir(parents=True)
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    (project / ".ract" / "policy.yaml").write_text(
        "version: 1\n"
        f"binding:\n  project_root: '{os.path.realpath(project)}'\n"
        f"issued_at: {now:%Y-%m-%dT%H:%M:%SZ}\n"
        f"expires_at: {now + timedelta(days=30):%Y-%m-%dT%H:%M:%SZ}\n"
        f"key_id: {key.key_id}\n"
        "sandbox: best_effort\n",
        encoding="utf-8",
    )
    sign(project, unlock(PASS, config=cfg), key)
    return project


def test_g1_an_unreadable_revocation_list_refuses_a_good_grant(
    tmp_path: Path, cfg: Path
) -> None:
    project = _signed_project(tmp_path, cfg)
    assert load_grant(project, config=cfg).holds
    (cfg / "revoked_grants.json").write_text("{not json", encoding="utf-8")
    state = load_grant(project, config=cfg)
    assert (
        state.status == "invalid" and "revocation list cannot be read" in state.reason
    )


def test_g1_revoke_writes_the_list_atomically(
    tmp_path: Path, cfg: Path, monkeypatch
) -> None:
    project = _signed_project(tmp_path, cfg)
    replaced: list[str] = []
    real = os.replace
    monkeypatch.setattr(
        "ract.policy.grant.os.replace",
        lambda a, b: replaced.append(str(b)) or real(a, b),
    )
    revoke(project, config=cfg)
    assert any(p.endswith("revoked_grants.json") for p in replaced)


def test_g3_the_pin_is_of_the_bytes_the_decision_verified(
    tmp_path: Path, cfg: Path
) -> None:
    project = _signed_project(tmp_path, cfg)
    state = load_grant(project, config=cfg)
    assert state.pin == pin_digest(project)
    saved = tmp_path / "saved"
    shutil.copytree(project / ".ract", saved)
    (project / ".ract" / "policy.yaml").write_text("swapped\n", encoding="utf-8")
    # A later read sees other bytes; the decision's pin stays that of what it verified.
    assert pin_digest(project) != state.pin


def test_u1_the_unlock_window_is_capped_and_doctor_says_so(cfg: Path) -> None:
    from ract.policy.unlock import window_minutes, window_note

    generate(PASS, config=cfg)
    path = cfg / "config.yaml"
    path.write_text(
        path.read_text(encoding="utf-8") + "unlock_window_minutes: 600\n",
        encoding="utf-8",
    )
    assert window_minutes("enforced", cfg) == 60
    assert (
        window_note(cfg)
        == "unlock_window_minutes 600 is read as 60, the most it may be"
    )
