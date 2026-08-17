"""Sandbox signing key — the environment attester (SUBSTRATE §7.1).

Every run mints one ``SandboxKey`` at first sandbox entry. The private
material lives on disk under ``.rack/sandbox/<run_id>.key`` and is
consumed only by the sandbox process; the model layer never sees it. The
raw 32-byte public key is embedded in every v2 Rootknot the run
produces, so the environment signature verifies offline against the
sidecar alone (module_06 lateral chain branch C).

At run completion, the private key is archived under
``.rack/sandbox/archive/<run_id>.key`` so rootknots signed during that
run remain verifiable. The SQLite provenance index carries the key id
(``sha256(pubkey)``) so a rootknot can be resolved back to the pubkey
that attested it (lateral chain branch B).

Reference sources:

- SUBSTRATE spec §7.1 (Environment as attester).
- RFC 8032 for Ed25519 (IETF).
- ``cryptography`` Python library public docs: ``https://cryptography.io/``.
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


class SandboxKey:
    """Ed25519 signing key held inside the sandbox process for one run.

    The signing surface is deliberately minimal: ``sign(bytes) -> bytes``
    plus ``public`` (raw 32 bytes) and ``key_id`` (SHA-256 of the raw
    pubkey). The Rootknot's ``environment_signature`` is produced by
    calling ``sign`` on the same canonical bytes the generator signature
    is produced from.
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
    ) -> "SandboxKey":
        """Generate a fresh ``SandboxKey`` for ``run_id``.

        The private material is written under
        ``<workspace_root>/.rack/sandbox/<run_id>.key`` with ``0600``
        permissions (POSIX). The sandbox process is the only reader; the
        capability manifest for the run explicitly refuses read of
        ``.rack/sandbox/`` so the model can never see the file.
        """
        if len(run_id) != 16:
            raise ValueError("run_id must be a 16-byte UUID")
        if workspace_root is None:
            workspace_root = Path.cwd()
        sandbox_dir = Path(workspace_root) / ".rack" / "sandbox"
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            sandbox_dir.chmod(0o700)
        key_path = sandbox_dir / f"{run_id.hex()}.key"
        if key_path.exists():
            pem = key_path.read_bytes()
            priv = serialization.load_pem_private_key(pem, password=None)
            if not isinstance(priv, Ed25519PrivateKey):
                raise ValueError("Stored sandbox key is not an Ed25519 private key")
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
    def load_archived(cls, run_id: bytes, workspace_root: Path) -> "SandboxKey | None":
        """Load an archived key for ``run_id`` from ``.rack/sandbox/archive/``.

        Returns ``None`` if no archived key exists — the caller then falls
        back to the pubkey embedded in the v2 sidecar (SUBSTRATE §7.2 +
        module_06 lateral chain branch C).
        """
        archive = (
            Path(workspace_root)
            / ".rack"
            / "sandbox"
            / "archive"
            / f"{run_id.hex()}.key"
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
        """Move the private key under ``.rack/sandbox/archive/``.

        Called by the loop's finalizer at run completion so the key file
        does not linger in the live sandbox directory. The archived
        pubkey remains resolvable by ``key_id`` for future verification.
        Returns the archive path.
        """
        if workspace_root is None:
            # ``<workspace_root>/.rack/sandbox/<run_id>.key`` — walk up two
            # to recover the workspace root.
            workspace_root = self._key_path.parent.parent.parent
        archive_dir = Path(workspace_root) / ".rack" / "sandbox" / "archive"
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


# RACT 0.4.0
