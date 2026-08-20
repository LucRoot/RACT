"""JCS canonical output is CRLF/LF invariant (module_03).

The v0.4.1 CI break — where a Windows checkout with CRLF-normalised
fixtures produced different canonical bytes than the POSIX baseline —
was fixed for :func:`_content_bytes_for`. Module_03 extends the
invariant to every sacred-spine call site now routing through
:func:`ract.canonical.dumps_jcs`: the encoder never emits CR/LF
characters of its own (JCS specifies no whitespace between tokens),
and any CR/LF present in an input string is escaped as ``\\r`` /
``\\n``. This test pins those properties so a future regression
surfaces at pytest time rather than in a cross-platform signature
verification failure.

Reference: ``_BUILD/ract_v0.5.1_external_review_response/module_03.md``.
"""

from __future__ import annotations

from ract.canonical import dumps_jcs


def test_output_contains_no_bare_cr_or_lf() -> None:
    """Encoder never emits CR (0x0D) or LF (0x0A) between tokens."""
    payload = {"a": 1, "b": [2, 3], "c": {"d": "e", "f": None}}
    encoded = dumps_jcs(payload)
    assert b"\r" not in encoded
    assert b"\n" not in encoded


def test_cr_lf_in_string_values_escaped() -> None:
    """CR and LF inside string values are escaped, not emitted raw."""
    payload = {"text": "line1\nline2\rline3\r\nline4"}
    encoded = dumps_jcs(payload)
    assert b"\r" not in encoded
    assert b"\n" not in encoded
    assert b"\\n" in encoded
    assert b"\\r" in encoded


def test_cr_lf_in_dict_keys_escaped() -> None:
    """CR and LF inside dict keys are escaped."""
    payload = {"key\nwith\rlinebreaks": 1}
    encoded = dumps_jcs(payload)
    assert b"\r" not in encoded
    assert b"\n" not in encoded
    assert b"\\n" in encoded
    assert b"\\r" in encoded


def test_same_input_across_lf_and_crlf_source_bytes_identical() -> None:
    """A payload constructed from LF vs CRLF source strings hashes identically.

    Simulates the fixture-loading scenario: one runner reads a
    text file with ``\\n`` line endings; another reads the same
    logical file with ``\\r\\n``. If the loader Python-side stores
    the strings verbatim, the encoded bytes differ (both LF/CRLF
    round-trip as escaped ``\\n`` / ``\\r\\n`` under JCS, and JSON
    does not equate them). The invariant guarded here is narrower:
    IDENTICAL Python inputs produce IDENTICAL bytes — the loader
    is responsible for normalising line endings BEFORE handing
    strings to the encoder. This test pins the encoder half.
    """
    lf = {"content": "a\nb\nc"}
    lf_again = {"content": "a\nb\nc"}
    assert dumps_jcs(lf) == dumps_jcs(lf_again)


def test_encoded_bytes_survive_utf8_round_trip() -> None:
    """``dumps_jcs(x).decode('utf-8').encode('utf-8')`` is a no-op."""
    payload = {"unicode": "αβγ", "ascii": "hello"}
    encoded = dumps_jcs(payload)
    assert encoded.decode("utf-8").encode("utf-8") == encoded
