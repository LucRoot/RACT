"""Ed25519 session keys for signing RACT provenance capabilities."""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ract.core.types import Digest, digest_bytes


class SessionKey:
    """A session-bound Ed25519 signing key persisted under XDG state."""

    __slots__ = ("_private_key", "_key_path")

    def __init__(self, private_key: Ed25519PrivateKey, key_path: Path) -> None:
        self._private_key = private_key
        self._key_path = key_path

    @classmethod
    def load_or_create(
        cls,
        session_id: bytes,
        state_dir: Path | None = None,
    ) -> SessionKey:
        """Load an existing session key or create and persist a new one."""
        if state_dir is None:
            state_dir = _default_state_dir()
        key_dir = state_dir / "keys"
        key_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            key_dir.chmod(0o700)
        key_path = key_dir / f"{session_id.hex()}.pem"
        if key_path.exists():
            pem = key_path.read_bytes()
            private_key = serialization.load_pem_private_key(pem, password=None)
            if not isinstance(private_key, Ed25519PrivateKey):
                raise ValueError("Stored key is not an Ed25519 private key")
            return cls(private_key, key_path)
        private_key = Ed25519PrivateKey.generate()
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        key_path.write_bytes(pem)
        if os.name != "nt":
            key_path.chmod(0o600)
        return cls(private_key, key_path)

    def public_key_bytes(self) -> bytes:
        """Return the raw 32-byte Ed25519 public key."""
        return self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def public_key_id(self) -> Digest:
        """Return the SHA256 digest of the public key bytes."""
        return digest_bytes(self.public_key_bytes())

    def sign(self, message: bytes) -> bytes:
        """Sign ``message`` and return the 64-byte Ed25519 signature."""
        return self._private_key.sign(message)

    @staticmethod
    def verify(message: bytes, signature: bytes, pubkey: bytes) -> bool:
        """Verify ``signature`` over ``message`` with ``pubkey``."""
        return verify(message, signature, pubkey)


def _default_state_dir() -> Path:
    """Return the platform-specific XDG state directory for RACT."""
    if os.name == "nt":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "ract"
        return Path.home() / "AppData/Local/ract"
    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home) / "ract"
    return Path.home() / ".local/state/ract"


def verify(message: bytes, signature: bytes, pubkey: bytes) -> bool:
    """Verify an Ed25519 signature; return False on any failure."""
    try:
        public_key = Ed25519PublicKey.from_public_bytes(pubkey)
        public_key.verify(signature, message)
    except Exception:
        return False
    return True


# RACT 0.2.0
