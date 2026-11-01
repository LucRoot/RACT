"""The operator key: Ed25519, encrypted with a passphrase, outside every workspace (ADR-0048 D2).

LR:: ``ract policy keygen`` creates the pair in the user config directory
(``<config>/operator/operator.key.json``) and pins the public key in
``<config>/config.yaml``. The private key is never stored in the clear: the
file is ``ract-operator-key/1``, the 32 raw private bytes sealed with
AES-256-GCM under a key derived from the passphrase with scrypt (a
memory-hard KDF), with the header (format, key id, public key) as
associated data, so a file whose header was swapped does not open. The
format was approved in D-123 (G-209), with ADR-0048 D2 amended to name
it: the ADR's earlier "scrypt through BestAvailableEncryption" does not
exist in the installed library, whose PKCS8 encryption is PBKDF2.

The key file is untrusted data (D-123): at most 4 KiB, a closed schema, no
link; the KDF parameters it stores are used, and a file asking for less
than n = 2^15 (or for absurd memory) is refused, so a planted weak file
cannot lower the cost. Every failure to open it with a passphrase gives the
same message, which does not say which part failed.

The passphrase is read only from a terminal (``read_passphrase``): a
non-TTY stdin is refused and no environment variable supplies it. Wrong
passphrase, damaged file and missing file each raise their own error with a
hint. Rotation keeps the old file under ``operator/retired/`` and pins the
new key; grants signed with the old key stop verifying.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from ract.atomic_write import write_atomic
from ract.policy import config_dir

FORMAT = "ract-operator-key/1"
KEY_FILE = "operator.key.json"
# scrypt cost: about 128 MiB and well under a second on a laptop (RFC 7914
# section 2 discusses the parameters; n = 2^17 is the interactive-login
# order of magnitude).
SCRYPT_N = 2**17
SCRYPT_R = 8
SCRYPT_P = 1
# A stored file may use other parameters, within these bounds (D-123).
MIN_SCRYPT_N = 2**15
MAX_SCRYPT_N = 2**20
MAX_SCRYPT_R = 16
MAX_SCRYPT_P = 4
# scrypt needs about 128 * n * r bytes; a stored file may ask for at most this
# (G-213 K3), so a planted file cannot make an unlock take gigabytes.
MAX_SCRYPT_MEMORY = 512 * 1024 * 1024
MAX_KEY_FILE_BYTES = 4096
MIN_PASSPHRASE = 8
WARN_PASSPHRASE = 12
_FILE_KEYS = {
    "format",
    "key_id",
    "public_key",
    "created_at",
    "kdf",
    "cipher",
    "ciphertext",
}
_KDF_KEYS = {"name", "n", "r", "p", "salt"}
_CIPHER_KEYS = {"name", "nonce"}
_OPEN_FAILED = (
    "the passphrase does not open the operator key",
    "type it again; if it is lost, `ract policy keygen --rotate` makes a new key "
    "and every grant needs signing again",
)


class OperatorKeyError(Exception):
    """A key operation that cannot go on; ``hint`` says what to do."""

    def __init__(self, message: str, hint: str) -> None:
        super().__init__(message)
        self.hint = hint


class NoOperatorKey(OperatorKeyError):
    pass


class WrongPassphrase(OperatorKeyError):
    pass


class PassphraseNeedsTerminal(OperatorKeyError):
    pass


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: object, what: str) -> bytes:
    if not isinstance(text, str):
        raise OperatorKeyError(
            f"the key file's {what} is missing", "run `ract policy keygen --rotate`"
        )
    try:
        return base64.b64decode(text, validate=True)
    except ValueError as exc:
        raise OperatorKeyError(
            f"the key file's {what} is not base64: {exc}",
            "run `ract policy keygen --rotate`",
        ) from exc


def key_id(public_key: bytes) -> str:
    """``ed25519:`` and the first 16 hex digits of the public key's SHA-256."""
    return "ed25519:" + hashlib.sha256(public_key).hexdigest()[:16]


def operator_dir(config: Path | None = None) -> Path:
    return (config or config_dir()) / "operator"


@dataclass(frozen=True)
class PublicKey:
    key_id: str
    public_key: bytes

    def verify(self, signature: bytes, message: bytes) -> bool:
        try:
            Ed25519PublicKey.from_public_bytes(self.public_key).verify(
                signature, message
            )
        except Exception:  # noqa: BLE001 - any failure is "does not verify"
            return False
        return True


def _derive(
    passphrase: str,
    salt: bytes,
    n: int = SCRYPT_N,
    r: int = SCRYPT_R,
    p: int = SCRYPT_P,
) -> bytes:
    import unicodedata

    # G-213 K4: the same typed passphrase is the same bytes on every system
    # (composed and decomposed characters alike).
    typed = unicodedata.normalize("NFKC", passphrase)
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(typed.encode("utf-8"))


def passphrase_warning(passphrase: str) -> str | None:
    """A warning for a passphrase that is allowed but short (D-123), or None."""
    if len(passphrase) < WARN_PASSPHRASE:
        return (
            f"warning: the passphrase has {len(passphrase)} characters; "
            f"{WARN_PASSPHRASE} or more is better, since it protects every grant you sign"
        )
    return None


def _aad(header: dict[str, Any]) -> bytes:
    """The whole header as associated data: every field but the ciphertext (G-213 K2)."""
    from ract.canonical import dumps_jcs

    return dumps_jcs({k: v for k, v in header.items() if k != "ciphertext"})


def _write_private(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.parent.chmod(0o700)
    temp = path.with_name(path.name + ".tmp")
    if temp.exists():
        temp.unlink()
    # G-213 K1: created owner-only before any byte is written, never another file.
    fd = os.open(
        temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600
    )
    with os.fdopen(fd, "wb") as fh:
        fh.write(json.dumps(data, indent=2).encode("utf-8"))
    os.replace(temp, path)
    if os.name == "nt":
        _restrict_windows_acl(path)


def _restrict_windows_acl(path: Path) -> bool:
    """Give only the current user access to *path* (D-123); False when it could not.

    LR:: On Windows any process running as the user can read the user's
    files, so the passphrase is the control that matters (ADR-0048 D2); the
    ACL still keeps other accounts out. ``icacls`` removes the inherited
    entries and grants the current user full control. The argv holds only
    this file's path and the user name from the environment.
    """
    import subprocess

    user = os.environ.get("USERNAME")
    if not user:
        print(
            "[operator_key] no USERNAME: the key file's ACL is left as inherited",
            flush=True,
        )
        return False
    done = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        print(
            f"[operator_key] the key file's ACL was not set: {done.stderr.strip()}",
            flush=True,
        )
        return False
    return True


def protection(config: Path | None = None) -> str:
    """How the key file is protected on this machine, in words, for ``ract doctor``."""
    path = operator_dir(config) / KEY_FILE
    if not path.is_file():
        return "no operator key on this machine; `ract policy keygen` makes one"
    if os.name != "nt":
        mode = path.stat().st_mode & 0o777
        if mode == 0o600:
            return "the key file is readable only by you (0600), and encrypted"
        return f"the key file's mode is {mode:o}, not 0600; it is encrypted"
    import subprocess

    done = subprocess.run(
        ["icacls", str(path)], capture_output=True, text=True, check=False
    )
    entries = [line for line in done.stdout.splitlines() if ":" in line and "(" in line]
    if done.returncode == 0 and len(entries) == 1:
        return (
            "the key file's ACL grants only you, and it is encrypted; any program "
            "running as you can still read it, so the passphrase is what protects it"
        )
    return (
        "the key file's ACL is not limited to you; it is encrypted, and any program "
        "running as you can read it, so the passphrase is what protects it"
    )


def generate(
    passphrase: str, *, config: Path | None = None, rotate: bool = False
) -> PublicKey:
    """Create the operator key pair, encrypt it, and pin its public key.

    Refuses to replace an existing key unless *rotate*; on rotation the old
    file moves to ``operator/retired/<key id>.json``.
    """
    if len(passphrase) < MIN_PASSPHRASE:
        raise OperatorKeyError(
            f"the passphrase has {len(passphrase)} characters; it needs {MIN_PASSPHRASE} or more",
            f"choose a longer passphrase ({WARN_PASSPHRASE} or more is better); it "
            "protects every grant you sign",
        )
    path = operator_dir(config) / KEY_FILE
    if path.exists():
        if not rotate:
            raise OperatorKeyError(
                f"an operator key already exists ({load_public(config).key_id})",
                "use `ract policy keygen --rotate` to replace it; grants signed with "
                "the old key then need signing again",
            )
        old = load_public(config)
        retired = (
            operator_dir(config) / "retired" / f"{old.key_id.replace(':', '-')}.json"
        )
        retired.parent.mkdir(parents=True, exist_ok=True)
        os.replace(path, retired)
    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    salt = os.urandom(16)
    nonce = os.urandom(12)
    header = {
        "format": FORMAT,
        "key_id": key_id(public),
        "public_key": _b64(public),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kdf": {
            "name": "scrypt",
            "n": SCRYPT_N,
            "r": SCRYPT_R,
            "p": SCRYPT_P,
            "salt": _b64(salt),
        },
        "cipher": {"name": "aes-256-gcm", "nonce": _b64(nonce)},
    }
    sealed = AESGCM(_derive(passphrase, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)).encrypt(
        nonce, raw, _aad(header)
    )
    _write_private(path, {**header, "ciphertext": _b64(sealed)})
    pinned = PublicKey(key_id(public), public)
    pin(pinned, config=config)
    return pinned


def _read(config: Path | None) -> dict[str, Any]:
    path = operator_dir(config) / KEY_FILE
    if path.is_symlink():
        raise OperatorKeyError(
            "the operator key file is a link; RACT reads only a regular file there",
            "remove the link and run `ract policy keygen --rotate`",
        )
    if not path.is_file():
        raise NoOperatorKey(
            "there is no operator key on this machine",
            "create one with `ract policy keygen` at a terminal",
        )
    try:
        if path.stat().st_size > MAX_KEY_FILE_BYTES:
            raise OperatorKeyError(
                f"the operator key file is larger than {MAX_KEY_FILE_BYTES} bytes",
                "run `ract policy keygen --rotate`",
            )
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OperatorKeyError(
            f"the operator key file cannot be read: {exc}",
            "run `ract policy keygen --rotate`",
        ) from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise OperatorKeyError(
            f"the operator key file is not {FORMAT}",
            "run `ract policy keygen --rotate`",
        )
    kdf, cipher = data.get("kdf"), data.get("cipher")
    if (
        set(data) != _FILE_KEYS
        or not isinstance(kdf, dict)
        or set(kdf) != _KDF_KEYS
        or not isinstance(cipher, dict)
        or set(cipher) != _CIPHER_KEYS
    ):
        raise OperatorKeyError(
            "the operator key file has fields RACT does not expect",
            "run `ract policy keygen --rotate`",
        )
    return data


def load_public(config: Path | None = None) -> PublicKey:
    """The operator's public key from the key file (no passphrase needed)."""
    data = _read(config)
    public = _unb64(data.get("public_key"), "public key")
    if key_id(public) != data.get("key_id"):
        raise OperatorKeyError(
            "the operator key file's key id does not match its public key",
            "run `ract policy keygen --rotate`",
        )
    return PublicKey(data["key_id"], public)


def unlock(passphrase: str, config: Path | None = None) -> Ed25519PrivateKey:
    """The private key, decrypted with *passphrase*; ``WrongPassphrase`` otherwise."""
    data = _read(config)
    kdf, cipher = data["kdf"], data["cipher"]
    n, r, p = kdf.get("n"), kdf.get("r"), kdf.get("p")
    if (
        kdf.get("name") != "scrypt"
        or cipher.get("name") != "aes-256-gcm"
        or not all(isinstance(v, int) and not isinstance(v, bool) for v in (n, r, p))
        or not (MIN_SCRYPT_N <= n <= MAX_SCRYPT_N)
        or n & (n - 1)
        or not (1 <= r <= MAX_SCRYPT_R)
        or not (1 <= p <= MAX_SCRYPT_P)
        or 128 * n * r > MAX_SCRYPT_MEMORY
    ):
        raise OperatorKeyError(
            "the operator key file names a KDF or cipher this RACT does not accept "
            "(scrypt with n from 2^15 to 2^20, AES-256-GCM)",
            "run `ract policy keygen --rotate`",
        )
    salt = _unb64(kdf.get("salt"), "salt")
    nonce = _unb64(cipher.get("nonce"), "nonce")
    sealed = _unb64(data.get("ciphertext"), "ciphertext")
    try:
        raw = AESGCM(_derive(passphrase, salt, n, r, p)).decrypt(
            nonce, sealed, _aad(data)
        )
        private = Ed25519PrivateKey.from_private_bytes(raw)
        public = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        if key_id(public) != data.get("key_id"):
            raise ValueError("the decrypted key is not the file's key")
    except (InvalidTag, ValueError) as exc:
        # One message whatever failed: it does not say which part (D-123).
        raise WrongPassphrase(*_OPEN_FAILED) from exc
    return private


# ------------------------------------------------------------------ pins


def _config_file(config: Path | None) -> Path:
    return (config or config_dir()) / "config.yaml"


def pin(key: PublicKey, *, config: Path | None = None) -> None:
    """Pin *key* as the operator key in the user config, replacing an earlier pin."""
    import yaml

    path = _config_file(config)
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise OperatorKeyError(
                f"the user config {path.name} cannot be read: {exc}",
                "fix or remove it, then run the command again",
            ) from exc
        if isinstance(loaded, dict):
            data = loaded
    data["operator_key"] = {"key_id": key.key_id, "public_key": _b64(key.public_key)}
    path.parent.mkdir(parents=True, exist_ok=True)
    # B-224: a fresh temporary file, never the predictable ".tmp" name.
    write_atomic(path, yaml.safe_dump(data, sort_keys=False).encode("utf-8"))


def pinned(config: Path | None = None) -> PublicKey | None:
    """The pinned operator key from the user config, or None when nothing is pinned."""
    import yaml

    path = _config_file(config)
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"[operator_key] the user config cannot be read: {exc}", flush=True)
        return None
    entry = data.get("operator_key") if isinstance(data, dict) else None
    if not isinstance(entry, dict):
        return None
    try:
        public = _unb64(entry.get("public_key"), "pinned public key")
    except OperatorKeyError as exc:
        print(f"[operator_key] {exc}", flush=True)
        return None
    if key_id(public) != entry.get("key_id") or len(public) != 32:
        return None
    return PublicKey(entry["key_id"], public)


# ------------------------------------------------------------------ the terminal


def read_passphrase(prompt: str = "Passphrase: ", *, confirm: bool = False) -> str:
    """Read a passphrase from the terminal without echo; refuse anything else.

    No environment variable and no pipe supplies it (ADR-0048 D2): a stdin
    that is not a terminal is refused before anything is read.
    """
    if not (sys.stdin is not None and sys.stdin.isatty()):
        raise PassphraseNeedsTerminal(
            "signing needs the passphrase typed at a terminal, and this stdin is not one",
            "run the command in a terminal; CI verifies grants with the pinned public "
            "key and never needs the private key",
        )
    first = getpass.getpass(prompt)
    if confirm:
        again = getpass.getpass("Again: ")
        if again != first:
            raise OperatorKeyError(
                "the two passphrases differ", "run the command again"
            )
    return first


__all__ = [
    "FORMAT",
    "NoOperatorKey",
    "OperatorKeyError",
    "PassphraseNeedsTerminal",
    "PublicKey",
    "WrongPassphrase",
    "generate",
    "key_id",
    "load_public",
    "passphrase_warning",
    "pin",
    "protection",
    "pinned",
    "read_passphrase",
    "unlock",
]
