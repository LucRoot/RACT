"""module_09 sacred-spine test: rootknot retrieval_attestation extension.

The retrieval_attestation field is an OPTIONAL extension on the
generator payload. Older sidecars — v1, v2, and v3 without the
field — must continue to verify unchanged. A v3 sidecar WITH the
field must include it inside canonical_bytes so the generator
signature actually covers it.

Master spec §Sacred spine invariants: the Rootknot 3-signature schema
stays intact; only the payload extends.
"""

from __future__ import annotations

import hashlib
import os

from ract.core.keys import SessionKey
from ract.core.rootknot import (
    Rootknot,
    bundle_digest,
    make_rootknot,
    make_rootknot_v3,
)
from ract.core.types import Digest, make_plan_id, make_step_id


class _SandboxStub:
    def __init__(self) -> None:
        self._key = SessionKey.load_or_create(os.urandom(16))

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)

    def public_key_bytes(self) -> bytes:
        return self._key.public_key_bytes()


class _AlmStub:
    def __init__(self) -> None:
        self._key = SessionKey.load_or_create(os.urandom(16))

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)

    def public_key_bytes(self) -> bytes:
        return self._key.public_key_bytes()


def test_older_sidecar_still_verifies() -> None:
    """Sacred-spine: v1 rootknots without retrieval_attestation verify.

    Named test the master spec §Sacred spine calls out. Constructs
    a v1 knot with the pre-module_09 constructor and confirms it
    still verifies under this module's code load.
    """
    key = SessionKey.load_or_create(os.urandom(16))
    knot = make_rootknot(
        key,
        workspace_path="/tmp/spine",
        artifact_digest=Digest(b"\x03" * 32),
        assumption_digest=Digest(b"\x04" * 32),
    )
    assert knot.retrieval_attestation is None
    assert knot.verify(key.public_key_bytes())


def test_v3_without_field_verifies() -> None:
    """A v3 knot constructed WITHOUT retrieval_attestation verifies."""
    key = SessionKey.load_or_create(os.urandom(16))
    sandbox = _SandboxStub()
    alm = _AlmStub()
    knot = make_rootknot_v3(
        key=key,
        sandbox_signer=sandbox,
        alm_signer=alm,
        workspace_path="/tmp/v3-no-attestation",
        artifact_digest=Digest(b"\x05" * 32),
        assumption_digest=Digest(b"\x06" * 32),
        acceptance_suite_digest=Digest(b"\x07" * 32),
        predicate_results=(),
        manifest_digest=Digest(b"\x08" * 32),
        gate_results=(),
    )
    assert knot.retrieval_attestation is None
    assert knot.verify(key.public_key_bytes())
    assert knot.verify_environment(sandbox.public_key_bytes())
    assert knot.verify_antilazy(alm.public_key_bytes())


def test_v3_with_attestation_included_in_canonical_bytes() -> None:
    """A v3 knot WITH retrieval_attestation binds it into canonical bytes."""
    key = SessionKey.load_or_create(os.urandom(16))
    sandbox = _SandboxStub()
    alm = _AlmStub()
    att = bundle_digest(b'{"chunks": [], "total_tokens": 0}')
    knot = make_rootknot_v3(
        key=key,
        sandbox_signer=sandbox,
        alm_signer=alm,
        workspace_path="/tmp/v3-with-attestation",
        artifact_digest=Digest(b"\x09" * 32),
        assumption_digest=Digest(b"\x0a" * 32),
        acceptance_suite_digest=Digest(b"\x0b" * 32),
        predicate_results=(),
        manifest_digest=Digest(b"\x0c" * 32),
        gate_results=(),
        retrieval_attestation=att,
    )
    assert knot.retrieval_attestation == att
    # Field is present in the signed bytes.
    assert (
        b'"retrieval_attestation":"' + att.hex().encode() + b'"'
        in knot.canonical_bytes()
    )
    # And the signature covers those bytes.
    assert knot.verify(key.public_key_bytes())
    assert knot.verify_environment(sandbox.public_key_bytes())
    assert knot.verify_antilazy(alm.public_key_bytes())


def test_attestation_field_changes_signature() -> None:
    """A knot with attestation has different signed bytes than one without."""
    key = SessionKey.load_or_create(os.urandom(16))
    sandbox = _SandboxStub()
    alm = _AlmStub()
    common_kwargs = dict(
        key=key,
        sandbox_signer=sandbox,
        alm_signer=alm,
        workspace_path="/tmp/differ",
        artifact_digest=Digest(b"\x11" * 32),
        assumption_digest=Digest(b"\x12" * 32),
        acceptance_suite_digest=Digest(b"\x13" * 32),
        predicate_results=(),
        manifest_digest=Digest(b"\x14" * 32),
        gate_results=(),
    )
    without = make_rootknot_v3(**common_kwargs)
    with_ = make_rootknot_v3(
        **common_kwargs, retrieval_attestation=bundle_digest(b"delta")
    )
    assert without.canonical_bytes() != with_.canonical_bytes()
    # Neither signature verifies the other's bytes.
    assert without.generator_signature != with_.generator_signature


def test_bundle_digest_is_sha256() -> None:
    """The bundle_digest helper is SHA-256 (32-byte Digest)."""
    payload = b'{"chunks": [1, 2, 3]}'
    digest = bundle_digest(payload)
    assert len(digest) == 32
    assert digest == Digest(hashlib.sha256(payload).digest())


def test_sign_preserves_attestation() -> None:
    """A knot.sign() call preserves the retrieval_attestation field."""
    key = SessionKey.load_or_create(os.urandom(16))
    att = bundle_digest(b"x")
    base = make_rootknot(
        key,
        workspace_path="/tmp/x",
        artifact_digest=Digest(b"\x03" * 32),
        assumption_digest=Digest(b"\x04" * 32),
    )
    knot = Rootknot(
        plan_id=make_plan_id(),
        step_id=make_step_id(),
        assumption_digest=Digest(b"\x02" * 32),
        generator=base.generator,
        parent_digests=(),
        workspace_path="/tmp/preserve",
        artifact_digest=Digest(b"\x03" * 32),
        created_at_ns=0,
        generator_signature=b"",
        retrieval_attestation=att,
    )
    signed = knot.sign(key)
    assert signed.retrieval_attestation == att


# RACT 0.5.0
