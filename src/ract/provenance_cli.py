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
from ract.core.rootknot import (
    _KNOWN_SCHEMA_VERSIONS,
    _ZERO_DIGEST,
    RootknotSchemaViolation,
)
from ract.core.types import digest_bytes


def _sidecar_path(artifact_path: Path) -> Path:
    """Return the sidecar path for ``artifact_path``.

    Sidecars live beside the artifact as ``.<name>.rootknot.json`` (see
    ``ProvenanceIndex.save``).
    """
    return artifact_path.parent / f".{artifact_path.name}.rootknot.json"


def verify_artifact(
    artifact_path: Path,
    workspace_root: Path | None = None,
    *,
    min_schema_version: int | None = None,
) -> tuple[bool, str]:
    """Verify the Rootknot for ``artifact_path``.

    Returns ``(ok, message)``. Checks:
      1. the artifact exists and its digest matches the rootknot's ``artifact_digest``,
      2. the signature verifies against the embedded generator public key,
      3. v0.5.2 module_01: the sidecar's ``schema_version`` is a
         known major (rejects an unknown v9 relabel per deep-audit
         A M-2) and, when ``min_schema_version`` is set, is at least
         that floor (rejects a v4-then-relabel-as-v1 DOWNGRADE per
         Ox Alpha M-1). ``min_schema_version=None`` (the default)
         preserves the v0.5.1 behaviour that v1/v2/v3 sidecars still
         verify without an explicit policy.

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
        except RootknotSchemaViolation as exc:
            # v0.5.2 module_01: surface the sharp diagnostic when
            # the index holds a v4-labelled sidecar with missing
            # fields (deep-audit A F-1) or an unknown-major relabel
            # (M-2), rather than a generic "index load failed".
            return False, (
                f"sidecar refused: {exc.reason}"
                if not exc.missing_fields
                else (
                    f"v4 schema-label but v4 fields empty: "
                    f"{exc.missing_fields}; the label carries no "
                    "attestation guarantee. Re-sign under a v3 factory "
                    "or supply the missing fields."
                )
            )
        except Exception as exc:  # noqa: BLE001 - surface any index failure
            return False, f"no sidecar and index load failed: {exc}"
        if knot is None:
            return False, (
                f"no rootknot for {artifact_path} (sidecar {sidecar.name} absent, "
                "not in index)"
            )
        return _check_knot(knot, artifact_path, min_schema_version)

    try:
        knot = _knot_from_json(payload)
    except RootknotSchemaViolation as exc:
        # v0.5.2 module_01: distinguish v4-label-mismatch from
        # unknown-major from generic parse failure so the operator
        # sees the specific attack shape.
        if exc.missing_fields:
            return False, (
                f"v4 schema-label but v4 fields empty: {exc.missing_fields}; "
                "the label carries no attestation guarantee (deep-audit A "
                "F-1). Re-sign under a v3 factory or supply the missing "
                "fields."
            )
        return False, (
            f"sidecar refused: {exc.reason}"
        )
    except Exception as exc:  # noqa: BLE001 - malformed sidecar is a verification failure
        return False, f"sidecar unparseable: {exc}"
    return _check_knot(knot, artifact_path, min_schema_version)


def _check_knot(
    knot, artifact_path: Path, min_schema_version: int | None = None
) -> tuple[bool, str]:
    # v0.5.2 module_01 (deep-audit A M-1 / M-2): schema-invariant
    # checks come first so a downgrade or unknown-major relabel is
    # reported with the sharp reason rather than shadowed by a
    # digest / signature message.
    if knot.schema_version not in _KNOWN_SCHEMA_VERSIONS:
        return False, (
            f"schema_version={knot.schema_version} not in "
            f"{sorted(_KNOWN_SCHEMA_VERSIONS)}; refusing rather than "
            "reinterpreting under weaker semantics (deep-audit A "
            "M-2). Upgrade the verifier or re-sign under an "
            "implemented major."
        )
    if (
        min_schema_version is not None
        and knot.schema_version < min_schema_version
    ):
        return False, (
            f"schema_version={knot.schema_version} below policy floor "
            f"{min_schema_version}; refusing the weaker attestation "
            "(deep-audit A M-1 DOWNGRADE defence)."
        )
    # v0.5.2 module_01 SP amendment (Q5 + Fork 3 gotcha #2
    # defense-in-depth for CLI): verifier-side v4-label-implies-v4-
    # fields with zero-digest sentinel refusal. Covers the
    # deserialisation-bypass path Ox Alpha warned about:
    # ``copy``/pickle restore skip ``__post_init__``, so a smuggled
    # v4 knot with empty or zero-digest fields could reach
    # ``_check_knot`` unchallenged.
    if knot.schema_version == 4:
        missing_v4: list[str] = []
        if not knot.workspace_digest or knot.workspace_digest == _ZERO_DIGEST:
            missing_v4.append("workspace_digest")
        if not knot.prompt_digest or knot.prompt_digest == _ZERO_DIGEST:
            missing_v4.append("prompt_digest")
        if not knot.run_id:
            missing_v4.append("run_id")
        if missing_v4:
            return False, (
                f"v4 schema-label but v4 fields empty or zero: "
                f"{missing_v4}; the label carries no attestation "
                "guarantee (deep-audit A F-1)."
            )
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
    # 3. Partial-attestation detection for v2/v3 sidecars (module_04, closes
    # module_03 Flagged gap #2 — silent-valid on unset extended fields).
    # A v2 sidecar promises the SUBSTRATE-era RK-3 bindings and a v3
    # sidecar adds the ALM-era AL-1 bindings; a rootknot at those schemas
    # whose extended digests / signatures are default (all-zero digests or
    # empty signature bytes) has skipped the environmental attestation the
    # sidecar shape claims to carry. The core digest+signature verified,
    # so the report is still ``valid`` — but the caller sees an explicit
    # ``partial:`` line naming every unset field so silent-partial is not
    # possible.
    partial_fields = _partial_extended_fields(knot)
    if partial_fields:
        joined = ", ".join(partial_fields)
        return True, f"valid (partial: {joined} unset)"
    return True, "valid"


def _partial_extended_fields(knot) -> list[str]:
    """Return the names of unset extended fields on a v2+/v3 rootknot.

    The v1 schema has no extended fields, so returns an empty list on any
    v1 knot. On v2 (SUBSTRATE) and v3 (ALM) knots, a default-value binding
    (all-zero digest or empty signature bytes) is treated as unset —
    the sidecar shape claimed the binding but the writer did not populate
    it, so the CLI names the specific field(s) rather than printing bare
    ``valid``.
    """
    if getattr(knot, "schema_version", 1) < 2:
        return []
    unset: list[str] = []
    if not knot.environment_signature:
        unset.append("environment_signature")
    if knot.acceptance_suite_digest == _ZERO_DIGEST:
        unset.append("acceptance_suite_digest")
    if knot.manifest_digest == _ZERO_DIGEST:
        unset.append("manifest_digest")
    if knot.schema_version >= 3:
        if not getattr(knot, "antilazy_signature", b""):
            unset.append("antilazy_signature")
    return unset


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
    for pem_path in list(key_dir.glob("*.pem")) + list(
        key_dir.glob("*.pem.archived-*")
    ):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )

            priv = serialization.load_pem_private_key(
                pem_path.read_bytes(), password=None
            )
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
    """Walk up from ``artifact_path`` to find the workspace state dir.

    v0.5.1 wiring module_10 (Lens A C2): the canonical name is
    ``.ract/``; a legacy ``.rack/`` directory is accepted as a fallback
    so a workspace that has not yet run through the migration shim
    still resolves. The workspace-state migration renames legacy
    directories in place on CLI dispatch.
    """
    from ract.workspace_state import LEGACY_STATE_DIR_NAME, WORKSPACE_STATE_DIR_NAME

    for parent in [artifact_path.parent, *artifact_path.parents]:
        if (parent / WORKSPACE_STATE_DIR_NAME).is_dir() or (
            parent / LEGACY_STATE_DIR_NAME
        ).is_dir():
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
    verify_p.add_argument(
        "--min-schema",
        type=int,
        default=None,
        help=(
            "Minimum acceptable schema_version. When set, the verifier "
            "refuses any sidecar labelled below this floor with a "
            "RK-DOWNGRADE-REFUSED reason -- closes the deep-audit A "
            "M-1 relabel-and-resign attack. Default (unset) preserves "
            "backward compatibility with v1/v2/v3 sidecars. Set to 4 "
            "for strict v0.5.1-and-later attestation deployments."
        ),
    )
    parsed = parser.parse_args(args)

    if parsed.action == "verify":
        artifact = Path(parsed.file).resolve()
        ws = Path(parsed.workspace).resolve() if parsed.workspace else None
        ok, message = verify_artifact(
            artifact,
            workspace_root=ws,
            min_schema_version=parsed.min_schema,
        )
        # Module_04: a v2/v3 sidecar with unset extended fields returns
        # ok=True with a ``valid (partial: … unset)`` message. The header
        # print reflects the message rather than a hardcoded ``valid`` so
        # the partial state is visible on the first line.
        if ok:
            header = "partial" if message.startswith("valid (partial:") else "valid"
        else:
            header = "invalid"
        print(header)
        print(message)
        return 0 if ok else 1
    return 1


# RACT 0.3.0


if __name__ == "__main__":
    sys.exit(_provenance_command(sys.argv[1:]))
