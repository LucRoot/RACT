"""ALM verifier signing key — the anti-lazy attester (ALM §5).

The ALM verifier process holds this key. It is separate from the sandbox
key ``ract.security.keys.SandboxKey`` on purpose: the sandbox attests
the environment (RK-3), the ALM verifier attests the thoroughness of the
completion (AL-1). Two distinct keys mean that compromising the sandbox
does not forge an anti-lazy signature and vice versa.

The private key persists under ``.ract/alm/<run_id>.key`` with the same
0600 permissions the sandbox key uses on POSIX. The capability manifest
in force for the model layer explicitly refuses read of ``.ract/alm/``
so the model never sees the private material.

Reference sources:

- ALM spec §5 (Three-Signature Rootknot).
- ``ract.security.keys.SandboxKey`` (the shape this mirrors).
- RFC 8032 (Edwards-curve Digital Signature Algorithm, ed25519).
- ``cryptography`` public docs: ``https://cryptography.io/``.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ract.core.types import Digest, digest_bytes


class AlmVerifierKey:
    """Ed25519 signing key held inside the ALM verifier process for one run.

    Distinct from ``SandboxKey``; the two keys attest different things.
    The signing surface matches ``SandboxKey`` deliberately so the
    Rootknot's ``attest_antilazy`` accepts either shape when a test
    swaps the signer.
    """

    __slots__ = ("_private_key", "_key_path")

    def __init__(self, private_key: Ed25519PrivateKey, key_path: Path) -> None:
        self._private_key = private_key
        self._key_path = key_path

    # ------------------------------------------------------------------
    # Generate / load
    # ------------------------------------------------------------------

    @classmethod
    def generate(
        cls, run_id: bytes, workspace_root: Path | None = None
    ) -> "AlmVerifierKey":
        """Generate a fresh ``AlmVerifierKey`` for ``run_id``.

        The private material is written under
        ``<workspace_root>/.ract/alm/<run_id>.key`` with ``0600``
        permissions on POSIX. Windows drops the ``chmod`` step; the
        directory is not shared with the model layer regardless of the
        underlying filesystem semantics.
        """
        if len(run_id) != 16:
            raise ValueError("run_id must be a 16-byte UUID")
        if workspace_root is None:
            workspace_root = Path.cwd()
        from ract.workspace_state import WORKSPACE_STATE_DIR_NAME

        alm_dir = Path(workspace_root) / WORKSPACE_STATE_DIR_NAME / "alm"
        alm_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            alm_dir.chmod(0o700)
        key_path = alm_dir / f"{run_id.hex()}.key"
        if key_path.exists():
            pem = key_path.read_bytes()
            priv = serialization.load_pem_private_key(pem, password=None)
            if not isinstance(priv, Ed25519PrivateKey):
                raise ValueError(
                    "Stored ALM verifier key is not an Ed25519 private key"
                )
            return cls(priv, key_path)
        priv = Ed25519PrivateKey.generate()
        pem = priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        key_path.write_bytes(pem)
        if os.name != "nt":
            key_path.chmod(0o600)
        return cls(priv, key_path)

    @classmethod
    def load_archived(
        cls, run_id: bytes, workspace_root: Path
    ) -> "AlmVerifierKey | None":
        """Load an archived key for ``run_id`` from ``.ract/alm/archive/``.

        Returns ``None`` if no archived key exists. Verification then
        falls back to the ALM pubkey embedded in the v3 sidecar (though
        that is trust-by-declaration; see the pubkey-registry note in
        the module_05 ``## Second Pass results`` section for the
        chain-of-custody design).
        """
        from ract.workspace_state import WORKSPACE_STATE_DIR_NAME

        archive = (
            Path(workspace_root) / WORKSPACE_STATE_DIR_NAME / "alm" / "archive" / f"{run_id.hex()}.key"
        )
        if not archive.exists():
            return None
        priv = serialization.load_pem_private_key(archive.read_bytes(), password=None)
        if not isinstance(priv, Ed25519PrivateKey):
            return None
        return cls(priv, archive)

    # ------------------------------------------------------------------
    # Archive on run completion
    # ------------------------------------------------------------------

    def archive(self, workspace_root: Path | None = None) -> Path:
        """Move the private key under ``.ract/alm/archive/``.

        Called by the loop finalizer so the key file does not linger in
        the live ``.ract/alm/`` directory across runs. The archived
        pubkey remains resolvable by ``key_id`` for future verification.
        """
        if workspace_root is None:
            workspace_root = self._key_path.parent.parent.parent
        from ract.workspace_state import WORKSPACE_STATE_DIR_NAME

        archive_dir = Path(workspace_root) / WORKSPACE_STATE_DIR_NAME / "alm" / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            archive_dir.chmod(0o700)
        target = archive_dir / self._key_path.name
        if self._key_path.exists():
            self._key_path.replace(target)
        self._key_path = target
        return target

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    @property
    def public(self) -> bytes:
        """Return the raw 32-byte Ed25519 public key."""
        return self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    @property
    def key_id(self) -> Digest:
        """Return the SHA-256 digest of the public key bytes."""
        return digest_bytes(self.public)

    def sign(self, message: bytes) -> bytes:
        """Sign ``message`` and return the 64-byte Ed25519 signature."""
        return self._private_key.sign(message)

    @staticmethod
    def verify(message: bytes, signature: bytes, pubkey: bytes) -> bool:
        """Verify ``signature`` over ``message`` with ``pubkey``.

        Returns ``False`` on any failure (invalid signature, malformed
        key, or crypto library error). Never raises.
        """
        try:
            public_key = Ed25519PublicKey.from_public_bytes(pubkey)
            public_key.verify(signature, message)
        except Exception:
            return False
        return True


__all__ = ["AlmVerifierKey"]


# RACT 0.4.0
