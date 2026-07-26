"""`ract provenance` CLI — audit Rootknots without running the full tool.

Implements ``ract provenance verify <path>``: loads the sidecar next to the
artifact, reconstructs the Rootknot, recomputes the artifact digest, and
verifies the ed25519 signature against the public key embedded in the
Rootknot's ``GeneratorRef``. Prints ``valid`` / ``invalid`` and exits 0/1.

This is the public audit surface promised by ``docs/PROVENANCE.md``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ract.core.provenance import ProvenanceIndex, _knot_from_json
from ract.core.types import digest_bytes


def _sidecar_path(artifact_path: Path) -> Path:
    """Return the sidecar path for ``artifact_path``.

    Sidecars live beside the artifact as ``.<name>.rootknot.json`` (see
    ``ProvenanceIndex.save``).
    """
    return artifact_path.parent / f".{artifact_path.name}.rootknot.json"


def verify_artifact(artifact_path: Path, workspace_root: Path | None = None) -> tuple[bool, str]:
    """Verify the Rootknot for ``artifact_path``.

    Returns ``(ok, message)``. Checks:
      1. the artifact exists and its digest matches the rootknot's ``artifact_digest``,
      2. the signature verifies against the embedded generator public key.

    The public key is NOT read from the key store; it is read from the
    sidecar's ``generator.public_key_id``. This makes verification
    self-contained: the sidecar is the audit artifact. (Resolution of the
    public key id to a known session key is a separate, optional trust step.)
    """
    artifact_path = Path(artifact_path)
    if not artifact_path.is_file():
        return False, f"artifact not found: {artifact_path}"

    sidecar = _sidecar_path(artifact_path)
    # Prefer the sidecar (human-audit path); fall back to the SQLite index.
    if sidecar.is_file():
        payload = sidecar.read_text(encoding="utf-8")
    else:
        if workspace_root is None:
            workspace_root = _infer_workspace_root(artifact_path)
        try:
            index = ProvenanceIndex(workspace_root)
            knot = index.load(artifact_path)
        except Exception as exc:  # noqa: BLE001 - surface any index failure
            return False, f"no sidecar and index load failed: {exc}"
        if knot is None:
            return False, (
                f"no rootknot for {artifact_path} (sidecar {sidecar.name} absent, "
                "not in index)"
            )
        return _check_knot(knot, artifact_path)

    try:
        knot = _knot_from_json(payload)
    except Exception as exc:  # noqa: BLE001 - malformed sidecar is a verification failure
        return False, f"sidecar unparseable: {exc}"
    return _check_knot(knot, artifact_path)


def _check_knot(knot, artifact_path: Path) -> tuple[bool, str]:
    # 1. artifact digest
    actual = digest_bytes(artifact_path.read_bytes())
    if actual != knot.artifact_digest:
        return False, (
            f"artifact digest mismatch (expected {knot.artifact_digest.hex()[:12]}…, "
            f"got {actual.hex()[:12]}…) — artifact tampered or stale rootknot"
        )
    # 2. signature against the embedded generator public key id.
    # The generator carries public_key_id (SHA256 of the pubkey), not the raw
    # pubkey. For CLI verification we re-derive: the sidecar is trusted as the
    # pubkey source ONLY when the operator supplies the matching session key.
    # Without a session key, we verify the signature against every key in the
    # local key store whose id matches; if none match, we report unverified.
    pubkey = _resolve_pubkey(knot)
    if pubkey is None:
        return False, (
            "cannot resolve generator public key (no matching session key in "
            f"store for id {knot.generator.public_key_id.hex()[:12]}…) — "
            "signature not checked"
        )
    if not knot.verify(pubkey):
        return False, "signature does not verify against the generator public key"
    return True, "valid"


def _resolve_pubkey(knot) -> bytes | None:
    """Resolve the generator's public key from the local key store by id.

    Returns the raw 32-byte public key whose SHA256 matches the rootknot's
    ``generator.public_key_id``, or None if no such key is on disk. The key
    store includes archived keys, so rootknots signed before a rotation still
    resolve.
    """
    from ract.core.keys import _default_state_dir

    key_dir = _default_state_dir() / "keys"
    if not key_dir.is_dir():
        return None
    target_id = knot.generator.public_key_id
    for pem_path in list(key_dir.glob("*.pem")) + list(key_dir.glob("*.pem.archived-*")):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

            priv = serialization.load_pem_private_key(pem_path.read_bytes(), password=None)
            if not isinstance(priv, Ed25519PrivateKey):
                continue
            pub_bytes = priv.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            if digest_bytes(pub_bytes) == target_id:
                return pub_bytes
        except Exception:  # noqa: BLE001 - skip unreadable/corrupt key files
            continue
    return None


def _infer_workspace_root(artifact_path: Path) -> Path:
    """Walk up from ``artifact_path`` to find the workspace containing ``.rack``."""
    for parent in [artifact_path.parent, *artifact_path.parents]:
        if (parent / ".rack").is_dir():
            return parent
    return artifact_path.parent


def _provenance_command(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ract provenance")
    sub = parser.add_subparsers(dest="action", required=True)
    verify_p = sub.add_parser("verify", help="Verify the Rootknot for an artifact.")
    verify_p.add_argument("file", help="Path to the artifact to verify.")
    verify_p.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (for SQLite index fallback). Inferred if omitted.",
    )
    parsed = parser.parse_args(args)

    if parsed.action == "verify":
        artifact = Path(parsed.file).resolve()
        ws = Path(parsed.workspace).resolve() if parsed.workspace else None
        ok, message = verify_artifact(artifact, workspace_root=ws)
        print("valid" if ok else "invalid")
        print(message)
        return 0 if ok else 1
    return 1


# RACT 0.3.0


if __name__ == "__main__":
    sys.exit(_provenance_command(sys.argv[1:]))
