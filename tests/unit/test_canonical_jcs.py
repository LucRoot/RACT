"""Regression tests for :mod:`ract.canonical` (module_03).

Covers RFC 8785 JCS conformance for the payload shapes RACT signs over:
sort ordering, string encoding, float edge cases, integer preservation,
NFC normalisation, and round-trip determinism. Cross-Python-version
determinism is covered indirectly here (the same repr rules apply on
every version >= 3.10) and directly in
``tests/unit/test_windows_line_endings.py`` via CRLF/LF invariants.

Reference: ``_BUILD/ract_v0.5.1_external_review_response/module_03.md``.
"""

from __future__ import annotations

import json

import pytest

from ract.canonical import (
    CanonicalJSONError,
    dumps_jcs,
    is_canonical,
    loads_jcs,
)


# ---------------------------------------------------------------------------
# RFC 8785 test vectors (subset — the appendix's representative shapes)
# ---------------------------------------------------------------------------


def test_empty_object_vector() -> None:
    """RFC 8785 §3.2.3 baseline: empty object serialises as two bytes."""
    assert dumps_jcs({}) == b"{}"


def test_empty_array_vector() -> None:
    """RFC 8785 §3.2.3 baseline: empty array serialises as two bytes."""
    assert dumps_jcs([]) == b"[]"


def test_primitive_vectors() -> None:
    """Simple primitives: null, booleans, small integers."""
    assert dumps_jcs(None) == b"null"
    assert dumps_jcs(True) == b"true"
    assert dumps_jcs(False) == b"false"
    assert dumps_jcs(0) == b"0"
    assert dumps_jcs(-1) == b"-1"
    assert dumps_jcs(42) == b"42"


def test_string_vector_ascii() -> None:
    """ASCII string emits with escapes for JSON-mandatory characters."""
    assert dumps_jcs("hello") == b'"hello"'
    assert dumps_jcs('"') == b'"\\""'
    assert dumps_jcs("\\") == b'"\\\\"'
    assert dumps_jcs("\n") == b'"\\n"'
    assert dumps_jcs("\t") == b'"\\t"'


def test_string_vector_unicode_bmp() -> None:
    """BMP characters emit as raw UTF-8 (no \\uXXXX escape mandated)."""
    # Greek small letter alpha (U+03B1) — UTF-8: 0xCE 0xB1.
    assert dumps_jcs("α") == b'"\xce\xb1"'


def test_string_vector_control_char_escape() -> None:
    """Sub-0x20 code points require \\uXXXX escape."""
    assert dumps_jcs("\x01") == b'"\\u0001"'
    assert dumps_jcs("\x1f") == b'"\\u001f"'


def test_object_vector_sort_codepoint() -> None:
    """Keys sort by Unicode code point (ASCII portion is stable)."""
    payload = {"b": 2, "a": 1, "c": 3}
    assert dumps_jcs(payload) == b'{"a":1,"b":2,"c":3}'


def test_object_vector_no_whitespace() -> None:
    """No insignificant whitespace anywhere in the output."""
    payload = {"a": [1, 2, {"b": True}], "c": None}
    assert dumps_jcs(payload) == b'{"a":[1,2,{"b":true}],"c":null}'


def test_array_vector_preserves_order() -> None:
    """Array element order is preserved; no sort applied."""
    assert dumps_jcs([3, 1, 2]) == b"[3,1,2]"


# ---------------------------------------------------------------------------
# Float edge cases (RFC 8785 §3.2.2.3 + ECMA-262)
# ---------------------------------------------------------------------------


def test_negative_zero_normalises_to_zero() -> None:
    """``-0.0`` → ``"0"`` per RFC 8785 §3.2.2.3."""
    assert dumps_jcs(-0.0) == b"0"
    assert dumps_jcs(0.0) == b"0"


def test_integer_valued_float_emits_integer_form() -> None:
    """``1.0`` and ``42.0`` emit without ``.0`` tail (ECMA-262)."""
    assert dumps_jcs(1.0) == b"1"
    assert dumps_jcs(-42.0) == b"-42"


def test_nan_raises_canonical_json_error() -> None:
    """NaN has no canonical JSON representation."""
    with pytest.raises(CanonicalJSONError, match="NaN"):
        dumps_jcs(float("nan"))


def test_positive_infinity_raises_canonical_json_error() -> None:
    """+Inf has no canonical JSON representation."""
    with pytest.raises(CanonicalJSONError, match="Infinity"):
        dumps_jcs(float("inf"))


def test_negative_infinity_raises_canonical_json_error() -> None:
    """-Inf has no canonical JSON representation."""
    with pytest.raises(CanonicalJSONError, match="Infinity"):
        dumps_jcs(float("-inf"))


def test_float_repr_shortest_round_trip() -> None:
    """A non-integer float round-trips through parse+dump byte-identically."""
    value = 3.141592653589793
    encoded = dumps_jcs(value)
    parsed = loads_jcs(encoded)
    assert parsed == value
    assert dumps_jcs(parsed) == encoded


# ---------------------------------------------------------------------------
# Integer preservation (lossless beyond safe range)
# ---------------------------------------------------------------------------


def test_large_integer_preserved_lossless() -> None:
    """Integers beyond 2**53 preserve exact digit sequence."""
    value = 2**60
    assert dumps_jcs(value) == b"1152921504606846976"


def test_negative_large_integer_preserved() -> None:
    """Negative large integers preserve leading minus + digits."""
    assert dumps_jcs(-(2**60)) == b"-1152921504606846976"


def test_bool_serialises_as_bool_not_int() -> None:
    """``bool`` is an ``int`` subclass in Python; must not emit ``"1"``."""
    assert dumps_jcs(True) == b"true"
    assert dumps_jcs(False) == b"false"


# ---------------------------------------------------------------------------
# Unicode NFC normalisation
# ---------------------------------------------------------------------------


def test_nfc_normalises_composed_and_decomposed() -> None:
    """Composed (single code point) and decomposed forms hash identically."""
    composed = "é"  # é as a single code point
    decomposed = "é"  # e + combining acute accent
    assert dumps_jcs(composed) == dumps_jcs(decomposed)


def test_nfc_normalises_dict_keys() -> None:
    """NFC applies to dict keys too — otherwise semantic equality breaks."""
    a = dumps_jcs({"é": 1})
    b = dumps_jcs({"é": 1})
    assert a == b


def test_nfc_collision_on_duplicate_keys_raises() -> None:
    """Two source keys collapsing to the same NFC form refuse silently drop."""
    payload = {"é": 1, "é": 2}
    with pytest.raises(CanonicalJSONError, match="Duplicate NFC"):
        dumps_jcs(payload)


# ---------------------------------------------------------------------------
# Round-trip fidelity
# ---------------------------------------------------------------------------


def test_round_trip_nested_structure() -> None:
    """Complex nested structure round-trips through parse + dump."""
    payload = {
        "z": [1, 2, {"nested": True, "arr": [None, 0.5, "hi"]}],
        "a": "first",
        "": "empty-key",
    }
    encoded = dumps_jcs(payload)
    parsed = loads_jcs(encoded)
    assert dumps_jcs(parsed) == encoded
    assert is_canonical(encoded) is True


def test_is_canonical_rejects_unsorted() -> None:
    """Unsorted keys → is_canonical returns False."""
    unsorted = b'{"b":2,"a":1}'
    assert is_canonical(unsorted) is False


def test_is_canonical_rejects_whitespace() -> None:
    """Insignificant whitespace → is_canonical returns False."""
    whitespaced = b'{"a": 1}'
    assert is_canonical(whitespaced) is False


def test_is_canonical_rejects_malformed() -> None:
    """Malformed input returns False (never raises)."""
    assert is_canonical(b"not json") is False
    assert is_canonical(b"") is False


def test_is_canonical_accepts_canonical() -> None:
    """A byte string produced by dumps_jcs passes is_canonical."""
    encoded = dumps_jcs({"z": 1, "a": [1, 2]})
    assert is_canonical(encoded) is True


# ---------------------------------------------------------------------------
# Sort ordering — codepoint vs lexicographic
# ---------------------------------------------------------------------------


def test_sort_order_is_codepoint_not_case() -> None:
    """Uppercase letters (U+0041+) sort before lowercase (U+0061+)."""
    payload = {"a": 1, "B": 2, "b": 3, "A": 4}
    assert dumps_jcs(payload) == b'{"A":4,"B":2,"a":1,"b":3}'


def test_sort_order_digits_before_letters() -> None:
    """Digits (U+0030+) sort before letters."""
    payload = {"a": 1, "1": 2}
    assert dumps_jcs(payload) == b'{"1":2,"a":1}'


def test_sort_order_special_chars() -> None:
    """Special characters within ASCII sort by code point."""
    payload = {"_a": 1, "-a": 2, ".a": 3}
    # "-" is U+002D, "." is U+002E, "_" is U+005F
    assert dumps_jcs(payload) == b'{"-a":2,".a":3,"_a":1}'


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_non_string_dict_key_raises() -> None:
    """Integer dict keys have no canonical form; must raise."""
    with pytest.raises(CanonicalJSONError, match="Non-string"):
        dumps_jcs({1: "one"})


def test_unsupported_type_raises() -> None:
    """Custom Python object without __json_snapshot__ raises."""

    class Custom:
        pass

    with pytest.raises(CanonicalJSONError, match="Unsupported"):
        dumps_jcs(Custom())


def test_json_snapshot_protocol_used() -> None:
    """__json_snapshot__ result is walked as JSON-native."""

    class Custom:
        def __json_snapshot__(self) -> object:
            return {"kind": "custom", "value": 42}

    assert dumps_jcs(Custom()) == b'{"kind":"custom","value":42}'


def test_cyclic_list_raises() -> None:
    """Cyclic list references are refused."""
    lst: list = [1]
    lst.append(lst)
    with pytest.raises(CanonicalJSONError, match="Cyclic"):
        dumps_jcs(lst)


def test_cyclic_dict_raises() -> None:
    """Cyclic dict references are refused."""
    d: dict = {"a": 1}
    d["self"] = d
    with pytest.raises(CanonicalJSONError, match="Cyclic"):
        dumps_jcs(d)


def test_supplementary_plane_key_refused() -> None:
    """Non-BMP dict keys refused pending v0.6 UTF-16 sort upgrade."""
    # U+1F600 (grinning face emoji) is supplementary plane.
    with pytest.raises(CanonicalJSONError, match="supplementary-plane"):
        dumps_jcs({"\U0001f600": 1})


# ---------------------------------------------------------------------------
# Determinism sanity — same input, byte-identical output twice
# ---------------------------------------------------------------------------


def test_two_calls_same_input_byte_identical() -> None:
    """Repeated calls on the same input produce byte-identical output."""
    payload = {"a": 1, "b": [2, 3], "c": {"d": "e"}}
    assert dumps_jcs(payload) == dumps_jcs(payload)


def test_dict_insertion_order_does_not_perturb() -> None:
    """Different insertion order → identical canonical bytes."""
    a = {"a": 1, "b": 2, "c": 3}
    b = {"c": 3, "b": 2, "a": 1}
    assert dumps_jcs(a) == dumps_jcs(b)


def test_tuple_and_list_serialise_identically() -> None:
    """Python tuples serialise the same as lists (JSON has no tuple)."""
    assert dumps_jcs((1, 2, 3)) == dumps_jcs([1, 2, 3])


# ---------------------------------------------------------------------------
# Interop — output parses under stdlib json
# ---------------------------------------------------------------------------


def test_output_parses_under_stdlib_json() -> None:
    """Every JCS output is legal JSON per stdlib json.loads."""
    payload = {"a": [1, 2.5, "s", True, None, {"k": "v"}]}
    encoded = dumps_jcs(payload)
    assert json.loads(encoded.decode("utf-8")) == payload
