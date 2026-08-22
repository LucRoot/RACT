"""Regression: ``ract provenance verify`` names unset v2/v3 extended fields.

Closes module_03 Flagged gap #2 (silent-valid on v2/v3 extended fields),
per module_04 (SUBSTRATE-era owner of the CLI verifier / RK-3 / AL-1
surface). The failure this test would have caught: a v2 sidecar whose
``environment_signature`` / ``acceptance_suite_digest`` / ``manifest_digest``
were default-value (empty bytes / all-zero digest) still printed bare
``valid`` because ``_check_knot`` inspected only the artifact digest and
the generator signature. An operator auditing a single artifact from a
v0.4 substrate run had no visibility that the extended attestation was
missing.

The fix adds ``_partial_extended_fields`` and threads the partial-state
signal through the CLI print path so the header line reads ``partial``
and the message names each unset field.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from ract.core.rootknot import _ZERO_DIGEST, make_rootknot
from ract.core.types import digest_bytes
from ract.provenance_cli import _partial_extended_fields


def _v1_knot(session_key):
    """A v1 rootknot has no extended fields (schema_version=1)."""
    return make_rootknot(
        session_key,
        workspace_path="module.py",
        artifact_digest=digest_bytes(b"content"),
        assumption_digest=digest_bytes(b"assume"),
    )


def test_partial_detector_v1_returns_empty(session_key) -> None:
    """A v1 rootknot has no extended fields; the detector must return []."""
    knot = _v1_knot(session_key)
    assert knot.schema_version == 1
    assert _partial_extended_fields(knot) == []


def test_partial_detector_v2_unset_fields_named(session_key) -> None:
    """A v2 rootknot with default extended fields lists them by name.

    A v2 sidecar with an empty ``environment_signature`` and all-zero
    ``acceptance_suite_digest`` / ``manifest_digest`` must be reported as
    ``partial`` naming each of those three fields. Silent-valid on this
    shape is exactly the failure the module_03 Second Pass surfaced.
    """
    knot = _v1_knot(session_key)
    # Simulate a v2 sidecar whose extended fields were never populated by
    # the writer (a v0.4 substrate shim that constructed a v2 knot but
    # forgot to run attest_environment).
    v2_default = replace(
        knot,
        schema_version=2,
        environment_signature=b"",
        acceptance_suite_digest=_ZERO_DIGEST,
        manifest_digest=_ZERO_DIGEST,
    )
    partial = _partial_extended_fields(v2_default)
    assert "environment_signature" in partial
    assert "acceptance_suite_digest" in partial
    assert "manifest_digest" in partial


def test_partial_detector_v2_all_set_returns_empty(session_key) -> None:
    """A v2 rootknot with populated extended fields is not partial."""
    knot = _v1_knot(session_key)
    v2_full = replace(
        knot,
        schema_version=2,
        environment_signature=b"\x11" * 64,
        acceptance_suite_digest=digest_bytes(b"suite"),
        manifest_digest=digest_bytes(b"manifest"),
    )
    assert _partial_extended_fields(v2_full) == []


def test_partial_detector_v3_names_antilazy_signature(session_key) -> None:
    """A v3 rootknot with an empty ``antilazy_signature`` names it.

    The ALM-era extension adds one signature; the CLI verifier must not
    silent-pass a v3 sidecar whose ALM attestation is unset.
    """
    knot = _v1_knot(session_key)
    v3_default = replace(
        knot,
        schema_version=3,
        environment_signature=b"\x11" * 64,
        acceptance_suite_digest=digest_bytes(b"suite"),
        manifest_digest=digest_bytes(b"manifest"),
        antilazy_signature=b"",
    )
    partial = _partial_extended_fields(v3_default)
    assert partial == ["antilazy_signature"]


def test_cli_print_header_says_partial_when_ok_message_starts_with_partial(
    monkeypatch, tmp_path, session_key, capsys
) -> None:
    """End-to-end: `ract provenance verify` prints ``partial`` header on
    a v2 sidecar with unset extended fields.

    We stub ``verify_artifact`` to return the exact shape ``_check_knot``
    now returns for a partial-attestation v2 rootknot; the CLI wrapper
    must print ``partial`` as the header (not ``valid``) so operators
    reading the first line see the state.
    """
    import ract.provenance_cli as pcli

    def fake_verify(artifact, workspace_root=None, *, min_schema_version=None):
        return True, "valid (partial: environment_signature, manifest_digest unset)"

    monkeypatch.setattr(pcli, "verify_artifact", fake_verify)

    fake_artifact = tmp_path / "x.txt"
    fake_artifact.write_text("x", encoding="utf-8")
    rc = pcli._provenance_command(["verify", str(fake_artifact)])
    captured = capsys.readouterr()
    assert rc == 0, "partial is a soft-pass; exit 0 preserved"
    lines = captured.out.strip().splitlines()
    assert lines[0] == "partial"
    assert "environment_signature" in lines[1]
    assert "manifest_digest" in lines[1]


# --- fixtures --------------------------------------------------------------


@pytest.fixture
def session_key():
    from ract.core.keys import SessionKey

    return SessionKey.load_or_create(b"\x00" * 16)


# RACT 0.4.1
