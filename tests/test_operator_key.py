"""B-111 (ADR-0048 D2): the operator key is encrypted, outside the workspace, and asks at a terminal.

Every key here is a throwaway in a temporary folder; the test run's user
config directory is a temporary folder too (conftest), so no test reaches
the operator's real key.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from ract.policy import config_dir
from ract.policy.operator_key import (
    FORMAT,
    NoOperatorKey,
    OperatorKeyError,
    PassphraseNeedsTerminal,
    WrongPassphrase,
    generate,
    load_public,
    pinned,
    read_passphrase,
    unlock,
)

PASS = "throwaway passphrase for a test"


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    return tmp_path / "config" / "ract"


def test_the_run_never_points_at_the_real_config_directory() -> None:
    assert "ract-test-config-" in str(config_dir())


def test_keygen_writes_an_encrypted_key_and_pins_it(cfg: Path) -> None:
    key = generate(PASS, config=cfg)

    data = json.loads(
        (cfg / "operator" / "operator.key.json").read_text(encoding="utf-8")
    )
    assert data["format"] == FORMAT and data["key_id"] == key.key_id
    assert data["kdf"]["name"] == "scrypt" and data["cipher"]["name"] == "aes-256-gcm"
    private = unlock(PASS, config=cfg)
    raw = private.private_bytes_raw()
    # The private bytes are nowhere in the file, raw or base64.
    text = (cfg / "operator" / "operator.key.json").read_bytes()
    assert raw not in text
    import base64

    assert base64.b64encode(raw) not in text
    assert pinned(config=cfg) == key == load_public(config=cfg)


def test_a_signature_made_with_the_unlocked_key_verifies_with_the_pin(
    cfg: Path,
) -> None:
    key = generate(PASS, config=cfg)
    signature = unlock(PASS, config=cfg).sign(b"grant")
    assert key.verify(signature, b"grant")
    assert not key.verify(signature, b"grant, edited")


def test_a_wrong_passphrase_is_refused(cfg: Path) -> None:
    generate(PASS, config=cfg)
    with pytest.raises(WrongPassphrase) as caught:
        unlock(PASS + "x", config=cfg)
    assert "keygen --rotate" in caught.value.hint


def test_a_short_passphrase_is_refused(cfg: Path) -> None:
    with pytest.raises(OperatorKeyError, match="8 or more"):
        generate("seven77", config=cfg)
    assert not (cfg / "operator").exists()


def test_no_key_says_how_to_make_one(cfg: Path) -> None:
    with pytest.raises(NoOperatorKey) as caught:
        unlock(PASS, config=cfg)
    assert "ract policy keygen" in caught.value.hint
    assert pinned(config=cfg) is None


def test_an_existing_key_is_not_replaced_without_rotate(cfg: Path) -> None:
    first = generate(PASS, config=cfg)
    with pytest.raises(OperatorKeyError, match="already exists"):
        generate(PASS, config=cfg)
    second = generate(PASS, config=cfg, rotate=True)
    assert second.key_id != first.key_id
    assert pinned(config=cfg) == second
    retired = cfg / "operator" / "retired" / f"{first.key_id.replace(':', '-')}.json"
    assert retired.is_file()


@pytest.mark.parametrize("field", ["public_key", "key_id", "format"])
def test_a_swapped_header_does_not_open(cfg: Path, field: str) -> None:
    generate(PASS, config=cfg)
    other = cfg.parent / "other"
    generate(PASS, config=other)
    path = cfg / "operator" / "operator.key.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    foreign = json.loads(
        (other / "operator" / "operator.key.json").read_text(encoding="utf-8")
    )
    data[field] = foreign[field] if field != "format" else "ract-operator-key/0"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(OperatorKeyError):
        unlock(PASS, config=cfg)


def test_weaker_kdf_parameters_in_the_file_are_refused(cfg: Path) -> None:
    generate(PASS, config=cfg)
    path = cfg / "operator" / "operator.key.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["kdf"]["n"] = 2
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(OperatorKeyError, match="KDF or cipher"):
        unlock(PASS, config=cfg)


def test_the_pin_keeps_other_user_settings(cfg: Path) -> None:
    cfg.mkdir(parents=True)
    (cfg / "config.yaml").write_text("deny:\n  - [git, push]\n", encoding="utf-8")
    generate(PASS, config=cfg)
    text = (cfg / "config.yaml").read_text(encoding="utf-8")
    assert "git" in text and "operator_key" in text


def test_a_tampered_pin_is_not_trusted(cfg: Path) -> None:
    generate(PASS, config=cfg)
    path = cfg / "config.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "key_id: ed25519:", "key_id: ed25519:0"
        ),
        encoding="utf-8",
    )
    assert pinned(config=cfg) is None


def test_the_passphrase_is_never_read_from_a_pipe_or_the_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("RACT_PASSPHRASE", PASS)
    monkeypatch.setattr("sys.stdin", io.StringIO(PASS + "\n"))
    asked: list[str] = []
    monkeypatch.setattr(
        "getpass.getpass", lambda prompt="": asked.append(prompt) or PASS
    )
    with pytest.raises(PassphraseNeedsTerminal) as caught:
        read_passphrase()
    assert asked == []  # refused before anything was read
    assert "terminal" in str(caught.value)


def test_a_terminal_passphrase_is_read_without_echo(monkeypatch) -> None:
    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("sys.stdin", Tty())
    answers = iter([PASS, PASS])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert read_passphrase(confirm=True) == PASS
    answers = iter([PASS, PASS + "x"])
    with pytest.raises(OperatorKeyError, match="differ"):
        read_passphrase(confirm=True)


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_the_key_file_is_private_on_posix(cfg: Path) -> None:
    generate(PASS, config=cfg)
    mode = (cfg / "operator" / "operator.key.json").stat().st_mode & 0o777
    assert mode == 0o600


# ------------------------------------------------------------------ D-123


def _file(cfg: Path) -> Path:
    return cfg / "operator" / "operator.key.json"


def _rewrite(cfg: Path, change) -> None:
    data = json.loads(_file(cfg).read_text(encoding="utf-8"))
    change(data)
    _file(cfg).write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("n", [2**14, 2**21, 2**15 + 1, 0])
def test_a_planted_file_cannot_lower_or_blow_up_the_cost(cfg: Path, n: int) -> None:
    generate(PASS, config=cfg)
    _rewrite(cfg, lambda d: d["kdf"].__setitem__("n", n))
    with pytest.raises(OperatorKeyError, match="does not accept"):
        unlock(PASS, config=cfg)


def test_the_stored_parameters_are_the_ones_used(cfg: Path, monkeypatch) -> None:
    # A file made with n = 2^15 (within bounds) opens with its own parameters.
    import ract.policy.operator_key as ok

    monkeypatch.setattr(ok, "SCRYPT_N", 2**15)
    generate(PASS, config=cfg)
    monkeypatch.setattr(ok, "SCRYPT_N", 2**17)
    assert json.loads(_file(cfg).read_text(encoding="utf-8"))["kdf"]["n"] == 2**15
    assert unlock(PASS, config=cfg) is not None


def test_the_key_file_is_untrusted_data(cfg: Path) -> None:
    generate(PASS, config=cfg)
    _rewrite(cfg, lambda d: d.__setitem__("note", "x"))
    with pytest.raises(OperatorKeyError, match="fields RACT does not expect"):
        load_public(config=cfg)
    _file(cfg).write_text("{" + " " * 5000 + "}", encoding="utf-8")
    with pytest.raises(OperatorKeyError, match="larger than 4096 bytes"):
        load_public(config=cfg)


def test_a_linked_key_file_is_refused(cfg: Path, tmp_path: Path) -> None:
    generate(PASS, config=cfg)
    real = tmp_path / "elsewhere.json"
    real.write_bytes(_file(cfg).read_bytes())
    _file(cfg).unlink()
    try:
        _file(cfg).symlink_to(real)
    except OSError:
        pytest.skip("this account cannot make a symbolic link")
    with pytest.raises(OperatorKeyError, match="is a link"):
        unlock(PASS, config=cfg)


def test_short_passphrases(cfg: Path) -> None:
    from ract.policy.operator_key import passphrase_warning

    with pytest.raises(OperatorKeyError, match="8 or more"):
        generate("1234567", config=cfg)
    assert passphrase_warning(
        "12345678"
    ) and "12 or more is better" in passphrase_warning("12345678")
    assert passphrase_warning("123456789012") is None
    generate("12345678", config=cfg)  # allowed, with the warning the CLI prints


def test_every_failure_to_open_says_the_same(cfg: Path) -> None:
    generate(PASS, config=cfg)
    messages = []
    with pytest.raises(WrongPassphrase) as wrong:
        unlock(PASS + "x", config=cfg)
    messages.append((str(wrong.value), wrong.value.hint))
    import base64

    def damage(d: dict) -> None:
        sealed = bytearray(base64.b64decode(d["ciphertext"]))
        sealed[0] ^= 1
        d["ciphertext"] = base64.b64encode(bytes(sealed)).decode("ascii")

    _rewrite(cfg, damage)
    with pytest.raises(WrongPassphrase) as damaged:
        unlock(PASS, config=cfg)
    messages.append((str(damaged.value), damaged.value.hint))
    assert messages[0] == messages[1]
    assert "does not open" in messages[0][0]


def test_doctor_says_how_the_key_file_is_kept(cfg: Path) -> None:
    from ract.policy.operator_key import protection

    assert "no operator key" in protection(config=cfg)
    generate(PASS, config=cfg)
    said = protection(config=cfg)
    assert "encrypted" in said
    if os.name == "nt":
        # The ACL claim depends on the machine: some Windows boxes let the
        # key limiting keep exactly the user; others (CI runners, domain
        # profiles) keep NT AUTHORITY\SYSTEM and BUILTIN\Administrators
        # with full control, and the honest answer there is "not limited
        # to you". Both wordings carry the same protection truth: the file
        # is encrypted and the passphrase is what protects it.
        assert "encrypted" in said and "passphrase is what protects it" in said
    else:
        assert "0600" in said
