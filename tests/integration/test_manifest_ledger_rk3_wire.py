"""Integration tests: RK-3 attest_environment -> manifest ledger append.

module_07 wires the Historical Manifest Ledger into ``attest_environment``
via an ambient :class:`ract.security.manifest_ledger.ManifestLedger`.
These tests exercise the wire end to end:

- ``make_rootknot_v4`` under a bound ledger + ambient run_id emits one
  ledger entry per attested knot;
- the ledger entry's ``rootknot_run_id`` matches the module_06 ambient;
- the ledger entry's ``rootknot_signature`` (base64) round-trips to
  the knot's ``environment_signature`` bytes;
- WAL cross-link fields are populated when a WAL is passed to the
  observer;
- no ledger entry lands when no ledger is bound (backward-compat with
  every pre-module_07 test that constructs v4 knots).
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from ract.core.assumptions_wal import AssumptionWal
from ract.core.keys import SessionKey
from ract.core.rootknot import make_rootknot_v2, make_rootknot_v4
from ract.core.types import Digest, digest_bytes
from ract.runtime import bind_run_id
from ract.security.keys import SandboxKey
from ract.security.manifest_ledger import (
    ManifestLedger,
    bind_ledger,
    count_wal_entries,
    record_environment_attestation,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_key() -> SessionKey:
    return SessionKey.load_or_create(b"\x00" * 16)


@pytest.fixture
def sandbox_key(tmp_path: Path) -> SandboxKey:
    return SandboxKey.generate(b"\x01" * 16, workspace_root=tmp_path)


class _StubAlmSigner:
    """Duck-typed ALM signer for building v4 knots without importing the real one."""

    def sign(self, message: bytes) -> bytes:
        import hashlib

        return hashlib.sha512(b"alm-" + message).digest()[:64]


@pytest.fixture
def alm_signer() -> _StubAlmSigner:
    return _StubAlmSigner()


def _mk_ledger(tmp_path: Path) -> ManifestLedger:
    return ManifestLedger(tmp_path / ".ract")


def _build_v4_knot(
    session_key: SessionKey,
    sandbox_key: SandboxKey,
    alm_signer: _StubAlmSigner,
    workspace: Path,
    manifest_digest: Digest,
    run_id: str | None = None,
):
    return make_rootknot_v4(
        key=session_key,
        sandbox_signer=sandbox_key,
        alm_signer=alm_signer,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(b"artifact"),
        assumption_digest=digest_bytes(b"assume"),
        acceptance_suite_digest=digest_bytes(b"suite"),
        predicate_results=(digest_bytes(b"pred-1"),),
        manifest_digest=manifest_digest,
        gate_results=(),
        workspace_digest=digest_bytes(b"workspace-canonical"),
        prompt_digest=digest_bytes(b"prompt-canonical"),
        run_id=run_id,
    )


# ---------------------------------------------------------------------------
# End-to-end wire
# ---------------------------------------------------------------------------


def test_v4_attest_environment_appends_via_ambient_ledger(
    tmp_path: Path,
    session_key: SessionKey,
    sandbox_key: SandboxKey,
    alm_signer: _StubAlmSigner,
) -> None:
    ledger = _mk_ledger(tmp_path)
    manifest_digest = digest_bytes(b"manifest-canonical-A")
    rid = "a" * 32
    with bind_run_id(rid), bind_ledger(ledger):
        knot = _build_v4_knot(
            session_key, sandbox_key, alm_signer, tmp_path, manifest_digest
        )
    entries = ledger.load()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["manifest_digest"] == bytes(knot.manifest_digest).hex()
    assert entry["rootknot_run_id"] == rid
    assert base64.b64decode(entry["rootknot_signature"]) == bytes(
        knot.environment_signature
    )
    assert entry["prev_ledger_hash"] == "GENESIS"


def test_no_append_when_no_ambient_ledger(
    tmp_path: Path,
    session_key: SessionKey,
    sandbox_key: SandboxKey,
    alm_signer: _StubAlmSigner,
) -> None:
    """Building a v4 knot without a bound ledger is a legal no-op."""
    ledger = _mk_ledger(tmp_path)  # unbound
    manifest_digest = digest_bytes(b"manifest-canonical-A")
    with bind_run_id("b" * 32):
        _build_v4_knot(session_key, sandbox_key, alm_signer, tmp_path, manifest_digest)
    assert ledger.load() == []


def test_v4_attest_idempotent_within_run(
    tmp_path: Path,
    session_key: SessionKey,
    sandbox_key: SandboxKey,
    alm_signer: _StubAlmSigner,
) -> None:
    """Two v4 knots under the same rid + same manifest emit one entry."""
    ledger = _mk_ledger(tmp_path)
    manifest_digest = digest_bytes(b"manifest-canonical-A")
    rid = "c" * 32
    with bind_run_id(rid), bind_ledger(ledger):
        _build_v4_knot(session_key, sandbox_key, alm_signer, tmp_path, manifest_digest)
        _build_v4_knot(session_key, sandbox_key, alm_signer, tmp_path, manifest_digest)
    assert len(ledger.load()) == 1


def test_wal_cross_link_populated_by_explicit_helper(
    tmp_path: Path,
    session_key: SessionKey,
    sandbox_key: SandboxKey,
    alm_signer: _StubAlmSigner,
) -> None:
    """Explicit record_environment_attestation with a WAL populates wal_cross_link."""
    ledger = _mk_ledger(tmp_path)
    wal = AssumptionWal(tmp_path / "wal_dir")
    wal.append("proposed", {"assumption_id": "a", "text": "t"})
    wal.append("accepted", {"assumption_id": "a"})
    assert count_wal_entries(wal) == 2

    manifest_digest = digest_bytes(b"manifest-canonical-B")
    rid = "d" * 32
    with bind_run_id(rid):
        knot = _build_v4_knot(
            session_key, sandbox_key, alm_signer, tmp_path, manifest_digest
        )
    # No ambient ledger bound during construction, so we call the
    # helper directly to test the WAL cross-link surface.
    result = record_environment_attestation(knot, ledger=ledger, wal=wal)
    assert result is not None
    entry = ledger.load()[0]
    assert entry["wal_cross_link"]["first_wal_seq"] == 2
    assert entry["wal_cross_link"]["last_wal_seq"] == 2


def test_v2_attest_still_no_ops_ledger(
    tmp_path: Path,
    session_key: SessionKey,
    sandbox_key: SandboxKey,
) -> None:
    """v2 knots lack ``run_id`` -- the ledger observer skips them cleanly."""
    ledger = _mk_ledger(tmp_path)
    with bind_ledger(ledger):
        make_rootknot_v2(
            key=session_key,
            sandbox_signer=sandbox_key,
            workspace_path="artifact.txt",
            artifact_digest=digest_bytes(b"artifact"),
            assumption_digest=digest_bytes(b"assume"),
            acceptance_suite_digest=digest_bytes(b"suite"),
            predicate_results=(digest_bytes(b"pred-1"),),
            manifest_digest=digest_bytes(b"manifest-canonical-C"),
        )
    assert ledger.load() == []


def test_manifest_bytes_stored_when_helper_provides_them(
    tmp_path: Path,
    session_key: SessionKey,
    sandbox_key: SandboxKey,
    alm_signer: _StubAlmSigner,
) -> None:
    """Explicit helper call with manifest_bytes writes CAS + references it."""
    ledger = _mk_ledger(tmp_path)
    from ract.canonical import dumps_jcs

    manifest_body = dumps_jcs(
        {"version": 1, "run_id": "e" * 32, "syscalls": {"seccomp_profile": "strict"}}
    )
    import hashlib

    manifest_digest = Digest(hashlib.sha256(manifest_body).digest())
    rid = "e" * 32
    with bind_run_id(rid):
        knot = _build_v4_knot(
            session_key, sandbox_key, alm_signer, tmp_path, manifest_digest
        )
    record_environment_attestation(knot, ledger=ledger, manifest_bytes=manifest_body)
    entry = ledger.load()[0]
    assert (
        entry["manifest_snapshot_ref"]
        == f"manifest_snapshots/{manifest_digest.hex()}.json"
    )
    assert ledger.read_snapshot(manifest_digest.hex()) == manifest_body


def test_multiple_attestations_chain_across_manifests(
    tmp_path: Path,
    session_key: SessionKey,
    sandbox_key: SandboxKey,
    alm_signer: _StubAlmSigner,
) -> None:
    """N attestations produce N entries with a valid Merkle chain."""
    ledger = _mk_ledger(tmp_path)
    rid = "f" * 32
    with bind_run_id(rid), bind_ledger(ledger):
        for i in range(3):
            _build_v4_knot(
                session_key,
                sandbox_key,
                alm_signer,
                tmp_path,
                digest_bytes(f"manifest-{i}".encode("utf-8")),
            )
    entries = ledger.load()
    assert len(entries) == 3
    result = ledger.verify_chain()
    assert result.valid is True
    assert result.tail_valid_count == 3


# RACT 0.5.1
