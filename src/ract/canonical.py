"""RFC 8785 JSON Canonicalization Scheme (JCS) — sacred-spine serializer.

Module_03 (v0.5.1 external review response) landing site for
REVIEW_4_UNKNOWN §D2 (deterministic JSON serialisation flaw). The
reviewer flagged that ``json.dumps(payload, sort_keys=True)`` — while
sufficient for root-level key order — does NOT guarantee cryptographic
canonicalisation: whitespace rules, float representation, escape
sequences, and Unicode normalisation can all shift between Python
minor versions, breaking signature verification across heterogeneous
runners. RFC 8785 (JSON Canonicalization Scheme, JCS) is the standard
fix. This module implements JCS as a stdlib-only in-tree serialiser so
RACT's sacred-spine payloads (Rootknot canonical bytes, AcceptanceSuite
digest, workspace_digest, WAL entries, plan step content_digest,
capability manifest, trace event hash, and receipt chain) all bind
identical bytes across CPython versions, PyPy, and Windows/POSIX
line-ending conventions.

Public surface
--------------

- :func:`dumps_jcs` — serialise a Python object to canonical UTF-8
  bytes. Bytes (not str) are canonical: JCS output is defined as an
  octet sequence.
- :func:`loads_jcs` — parse bytes-or-str via :func:`json.loads`. Parsing
  is not JCS-specific; the wrapper exists so callers use one namespace.
- :func:`is_canonical` — round-trip predicate: ``dumps_jcs(loads_jcs(x))
  == x``.
- :class:`CanonicalJSONError` — raised for every non-canonicalisable
  input (NaN/Inf, non-string dict keys, cycles, unsupported types).

Design decisions (Lateral chain PRE, branches carried into build)
-----------------------------------------------------------------

- **NFC everywhere.** RFC 8785 §3.2.2.2 requires Unicode NFC
  normalisation for both dict keys and string values. Some third-party
  JCS impls skip this (or gate it behind an opt-in flag). RACT applies
  it unconditionally — silent normalisation drift is exactly the class
  of bug D2 was written to close.
- **Sort by Unicode code-point order** (not UTF-16 code unit order).
  RFC 8785 specifies UTF-16 code unit order; for BMP-only strings
  (RACT's entire key vocabulary today: ASCII field names, hex digests,
  short natural-language strings) code-point and UTF-16 orderings are
  identical. Supplementary-plane characters (U+10000+) diverge — that
  edge is documented in the Flagged gaps carried to v0.6 and rejected
  by :func:`_check_sortable_keys` if it ever appears in practice.
- **Numbers via ECMA-262 shortest-round-trip.** Integers within
  ``[-(2**53 - 1), 2**53 - 1]`` serialise as decimal digits with no
  exponent. Integer-valued floats serialise identically to integers
  (``1.0 → "1"``). Non-integer floats use Python's :func:`repr` which
  has produced shortest-round-trip output since 3.1, with a fixed-form
  normalisation for magnitudes in ``[1e-6, 1e21)`` per ECMA-262
  ``Number.prototype.toString``. ``-0.0`` normalises to ``"0"``.
  ``NaN`` and ``+/-Inf`` raise :class:`CanonicalJSONError` — canonical
  JSON has no representation for them.
- **Strict JSON.** No ``default=`` fallback (module_02 SP Q4 lesson:
  ``default=str`` silent coercion is the class defect JCS is meant to
  close). Unsupported types raise :class:`CanonicalJSONError`.
- **Bytes output.** JCS is defined over octets; callers signing over
  the bytes should never re-encode. String output is available via
  ``dumps_jcs(x).decode('utf-8')`` when a text form is needed.
- **``__json_snapshot__`` protocol.** A user type may expose a
  ``__json_snapshot__(self) -> object`` method returning a JSON-native
  value. The serialiser invokes it once at descent time. This gives
  callers a stable extension surface without forcing every hash-input
  path to pre-flatten custom types.

Reference
---------

- RFC 8785 — JSON Canonicalization Scheme.
- ``_BUILD/ract_v0.5.1_external_review/REVIEW_4_UNKNOWN_REVIEWER.md``
  §D2 (origin defect).
- ``_BUILD/ract_v0.5.1_external_review_response/module_03.md``
  (build-chain evidence).
"""

from __future__ import annotations

import json
import math
import unicodedata
from typing import Any

__all__ = [
    "CanonicalJSONError",
    "dumps_jcs",
    "loads_jcs",
    "is_canonical",
]


class CanonicalJSONError(TypeError):
    """Raised for any input that has no RFC 8785 canonical form.

    Concrete triggers:

    - ``float('nan')`` / ``float('inf')`` / ``float('-inf')`` — canonical
      JSON has no encoding for non-finite numbers.
    - Non-string dict keys — JSON object keys are strings; any other
      key type has no unambiguous canonical encoding.
    - Cyclic references — an object graph containing itself has no
      finite serialisation.
    - Unsupported types (arbitrary Python objects without a
      ``__json_snapshot__`` protocol) — silent ``str()`` coercion was
      the module_02 SP Q4 defect; loud failure is the fix.

    Subclasses :class:`TypeError` so existing ``except TypeError``
    handlers (Python's json module raises the same base) keep working.
    """


# Integer-safe range under ECMA-262 (matches JSON.stringify behaviour
# in a browser). Beyond this range JavaScript loses precision on
# parse; JCS explicitly preserves the exact digit sequence so
# ``dumps_jcs(2**60) == b"1152921504606846976"``. RACT signs digests
# and epoch-ns timestamps that comfortably exceed the safe range —
# lossless integer preservation is load-bearing.
_INT_SAFE_MAX = (1 << 53) - 1
_INT_SAFE_MIN = -_INT_SAFE_MAX


# Sentinel object used by :func:`_walk` to detect cyclic references.
# The id-set membership check is O(1) and correctly handles the case
# where two distinct-but-equal containers share no cycle.
_CYCLE_SENTINEL = object()


def dumps_jcs(value: object) -> bytes:
    """Return the RFC 8785 JCS canonical encoding of ``value`` as UTF-8 bytes.

    Deterministic across CPython 3.10+, PyPy, and Windows/POSIX line
    endings (no CR/LF characters ever appear in the output). Sort order
    is Unicode code-point on dict keys.

    Parameters
    ----------
    value : object
        JSON-native value (``None``, ``bool``, ``int``, ``float``, ``str``,
        ``list``, ``tuple``, ``dict``) or an object implementing the
        ``__json_snapshot__() -> object`` protocol.

    Raises
    ------
    CanonicalJSONError
        For NaN/Inf, non-string dict keys, cycles, or unsupported types.
    """
    seen: set[int] = set()
    parts: list[str] = []
    _walk(value, seen, parts)
    text = "".join(parts)
    return text.encode("utf-8")


def loads_jcs(data: bytes | str) -> object:
    """Parse a JCS byte-or-str sequence.

    Delegates to :func:`json.loads`. JCS is a serialisation contract
    (one canonical output shape per input value); parsing is not
    JCS-specific. The wrapper exists so callers use a single import
    namespace (``from ract.canonical import dumps_jcs, loads_jcs``).
    """
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return json.loads(data)


def is_canonical(data: bytes) -> bool:
    """Return ``True`` iff ``data`` is a JCS-canonical serialisation.

    Round-trip predicate: parse ``data``, re-serialise via
    :func:`dumps_jcs`, and compare byte-for-byte. Returns ``False`` if
    the input parses but is not canonical (e.g., unsorted keys, extra
    whitespace, unnormalised Unicode). Returns ``False`` — never
    raises — if the input fails to parse.
    """
    try:
        parsed = loads_jcs(data)
        return dumps_jcs(parsed) == data
    except (CanonicalJSONError, ValueError, TypeError, UnicodeDecodeError):
        return False


# ---------------------------------------------------------------------------
# Internal encoder
# ---------------------------------------------------------------------------


def _walk(value: object, seen: set[int], out: list[str]) -> None:
    """Depth-first canonical serialiser writing into ``out``."""
    # Order matters: bool is a subclass of int in Python, so the bool
    # branch must fire first or ``True`` serialises as ``"1"``.
    if value is None:
        out.append("null")
        return
    if isinstance(value, bool):
        out.append("true" if value else "false")
        return
    if isinstance(value, int):
        out.append(_encode_int(value))
        return
    if isinstance(value, float):
        out.append(_encode_float(value))
        return
    if isinstance(value, str):
        out.append(_encode_string(value))
        return
    # __json_snapshot__ protocol: user types opt into the encoder by
    # returning a JSON-native representation. Invoked BEFORE the
    # container branches so a snapshot returning e.g. ``{"kind": ...}``
    # is walked as a dict, not as a bare object.
    #
    # Explicit opt-out: setting ``__json_snapshot__ = None`` (attribute,
    # not a callable) tells the encoder "this class deliberately
    # declines the protocol." The object then falls through to the
    # unsupported-type branch below — the caller must either pass a
    # JSON-native value or install a snapshot method. This lets a
    # subclass shadow a parent's snapshot without inheriting the
    # protocol.
    #
    # Cycle guard (module_03 SP Q2 DEFECT fix): a custom object whose
    # snapshot returns ``self`` (or a graph cycling back to ``self``)
    # would otherwise recurse forever. We add ``id(value)`` to the
    # ``seen`` set before invoking the snapshot, matching the discipline
    # applied to list/tuple/dict below. This also gives intra-run
    # memoisation for shared references — the snapshot is invoked once
    # per unique object instance per top-level ``dumps_jcs`` call.
    snapshot = getattr(value, "__json_snapshot__", None)
    if callable(snapshot):
        vid = id(value)
        if vid in seen:
            raise CanonicalJSONError(
                f"Cyclic reference detected via __json_snapshot__ on "
                f"{type(value).__name__!r} during canonical encode"
            )
        seen.add(vid)
        try:
            _walk(snapshot(), seen, out)
        finally:
            seen.discard(vid)
        return
    if isinstance(value, (list, tuple)):
        vid = id(value)
        if vid in seen:
            raise CanonicalJSONError(
                "Cyclic reference detected in list/tuple during canonical encode"
            )
        seen.add(vid)
        try:
            out.append("[")
            first = True
            for item in value:
                if not first:
                    out.append(",")
                first = False
                _walk(item, seen, out)
            out.append("]")
        finally:
            seen.discard(vid)
        return
    if isinstance(value, dict):
        vid = id(value)
        if vid in seen:
            raise CanonicalJSONError(
                "Cyclic reference detected in dict during canonical encode"
            )
        seen.add(vid)
        try:
            _encode_dict(value, seen, out)
        finally:
            seen.discard(vid)
        return
    raise CanonicalJSONError(
        f"Unsupported type in canonical encode: {type(value).__name__!r}. "
        f"JCS requires JSON-native types (None, bool, int, float, str, "
        f"list, tuple, dict) or a __json_snapshot__() method returning "
        f"one. Silent str() coercion is not permitted (module_02 SP Q4)."
    )


def _encode_dict(value: dict[Any, Any], seen: set[int], out: list[str]) -> None:
    """Encode a dict with NFC-normalised, code-point-sorted string keys."""
    # RFC 8785 §3.2.3: object keys are strings, sorted by UTF-16 code
    # unit order. All keys are NFC-normalised BEFORE sorting so that
    # semantically identical Unicode strings produce identical bytes.
    normalised: list[tuple[str, Any]] = []
    seen_keys: set[str] = set()
    for raw_key, item in value.items():
        if not isinstance(raw_key, str):
            raise CanonicalJSONError(
                f"Non-string dict key encountered: {type(raw_key).__name__!r}. "
                f"JCS object keys must be strings."
            )
        normalised_key = unicodedata.normalize("NFC", raw_key)
        if normalised_key in seen_keys:
            # Two source keys collapse to the same NFC form (e.g.,
            # composed vs decomposed accented character). Encoding
            # would silently drop one; refuse instead so the caller
            # sees the collision.
            raise CanonicalJSONError(
                f"Duplicate NFC-normalised key {normalised_key!r} in dict; "
                f"canonical encoding would be ambiguous."
            )
        seen_keys.add(normalised_key)
        normalised.append((normalised_key, item))
    # Sort by Unicode code point (BMP-safe surrogate: identical to
    # UTF-16 code unit order for the entire BMP). Supplementary-plane
    # keys are rejected by :func:`_check_bmp_only` — see Flagged gap
    # in module_03.md for the v0.6 UTF-16 sort upgrade.
    for key, _ in normalised:
        _check_bmp_only(key)
    normalised.sort(key=lambda kv: kv[0])
    out.append("{")
    first = True
    for key, item in normalised:
        if not first:
            out.append(",")
        first = False
        out.append(_encode_string(key))
        out.append(":")
        _walk(item, seen, out)
    out.append("}")


def _encode_int(value: int) -> str:
    """Encode a Python int as a JCS number literal.

    Integers of any magnitude serialise as their decimal digit sequence
    (no exponent, no leading zeros). Beyond ``_INT_SAFE_MAX`` an ECMA-262
    ``Number`` cannot round-trip losslessly, but JCS still preserves
    the digits — precision loss is a downstream concern for JavaScript
    consumers, not a serialisation ambiguity.
    """
    return str(value)


def _encode_float(value: float) -> str:
    """Encode a Python float as a JCS number literal.

    Rules:

    - ``NaN`` / ``+Inf`` / ``-Inf`` → :class:`CanonicalJSONError`.
    - ``-0.0`` and ``0.0`` → ``"0"``.
    - Integer-valued floats within safe range → decimal digit
      sequence with no ``.0`` tail (matches ``1.0 → "1"`` in
      ECMA-262 ``Number.prototype.toString``).
    - Otherwise ECMA-262 shortest-round-trip via Python's :func:`repr`,
      with exponent-vs-fixed normalisation for magnitudes in
      ``[1e-6, 1e21)``.
    """
    if math.isnan(value):
        raise CanonicalJSONError(
            "NaN is not representable in canonical JSON (RFC 8785)"
        )
    if math.isinf(value):
        raise CanonicalJSONError(
            "Infinity is not representable in canonical JSON (RFC 8785)"
        )
    if value == 0.0:
        # Handles both +0.0 and -0.0.
        return "0"
    # Integer-valued float (e.g., ``1.0``, ``42.0``): emit integer form.
    # ECMA-262 Number.prototype.toString omits the ``.0`` tail.
    if value.is_integer() and _INT_SAFE_MIN <= value <= _INT_SAFE_MAX:
        return str(int(value))
    return _js_number_repr(value)


def _js_number_repr(value: float) -> str:
    """Return the ECMA-262 ``Number.prototype.toString`` representation.

    Python's :func:`repr` produces shortest-round-trip output since 3.1
    (Gay's dtoa). For the vast majority of finite non-zero non-integer
    floats it matches ECMA-262 byte-for-byte. The one systematic
    divergence is exponent notation: Python emits ``"1e-05"`` and
    ``"1.5e-05"`` where ECMA-262 emits ``"0.00001"`` /
    ``"0.000015"`` (magnitude ``k`` in ``[-5, 20]`` -> fixed form).
    This helper normalises those to the ECMA-262 shape while
    PRESERVING the exact shortest-form digit sequence from
    :func:`repr` — reformatting via ``f"{v:.Nf}"`` would introduce
    spurious trailing digits (e.g., 1.5e-5 -> "0.000015000000000000001")
    and violate ECMA-262 "shortest that round-trips".

    Approach:

    - Extract the shortest mantissa digits from :func:`repr`
      (``"1.5e-05"`` -> digits ``"15"``, exponent -5, decimal
      position after digit 1).
    - Derive ``k = exponent + (int_part_length - 1)`` — the true
      ECMA-262 magnitude of the value, computed from the
      shortest-form digits without any float log10 rounding.
    - For ``-6 < k < 21`` emit fixed form by moving the decimal
      point; otherwise emit ``"<mantissa>e<sign><|exp|>"`` with
      explicit sign and no leading zeros in the exponent.
    """
    text = repr(value)
    if "e" not in text and "E" not in text:
        # Already in fixed form — nothing to normalise. ``repr`` for
        # a non-integer, non-exp double is exactly what ECMA-262 emits.
        return text
    # Split sign, mantissa, exponent.
    if text.startswith("-"):
        sign_str = "-"
        body = text[1:]
    else:
        sign_str = ""
        body = text
    mantissa, _, exp_part = body.lower().partition("e")
    exp = int(exp_part)
    if "." in mantissa:
        int_part, frac_part = mantissa.split(".", 1)
    else:
        int_part, frac_part = mantissa, ""
    # Shortest significant digits — leading digit + fractional digits.
    digits = int_part + frac_part
    # ECMA-262 magnitude k: floor(log10(|value|)). Since ``int_part``
    # from a Python repr in exp form is always a single non-zero
    # digit, ``k = exp + (len(int_part) - 1) = exp``. We keep the
    # general form so the derivation stays visible.
    k = exp + len(int_part) - 1
    # ECMA-262 §21.1.3.6 Number.prototype.toString: fixed form when
    # ``-6 <= k < 21`` (upper bound strict, matching ``(1e21).toString()
    # === "1e+21"`` but ``(1e20).toString() === "1e+20" .. no, 1e20 -> fixed``).
    # Lower bound INCLUSIVE at -6 so ``(1e-6).toString() === "0.000001"``
    # matches Node/browser behaviour; earlier draft had an off-by-one
    # here (module_03 SP Q3).
    if -6 <= k < 21:
        if k >= 0:
            # Digits before the decimal point: k+1.
            if k + 1 >= len(digits):
                # Pad with trailing zeros to reach the decimal point.
                fixed = digits + "0" * (k + 1 - len(digits))
            else:
                fixed = digits[: k + 1] + "." + digits[k + 1 :]
        else:
            # k in [-5, -1]: leading zeros required in front of digits.
            # E.g., k=-5, digits="15" -> "0.000015".
            fixed = "0." + "0" * (-k - 1) + digits
        # Strip any trailing zeros that came from padding (only matters
        # when frac_part was non-empty AND k+1 landed inside digits).
        if "." in fixed:
            fixed = fixed.rstrip("0").rstrip(".")
        if fixed in ("", "-"):
            fixed = "0"
        return sign_str + fixed
    # Exponential form. ECMA-262 emits ``"1e+21"``, ``"1e-7"`` — always
    # with an explicit sign and no zero-padding on the exponent.
    exp_sign = "+" if exp >= 0 else "-"
    return f"{sign_str}{mantissa}e{exp_sign}{abs(exp)}"


# ---------------------------------------------------------------------------
# String encoding
# ---------------------------------------------------------------------------


# Characters that require escaping per JSON §7 / ECMA-404. Everything
# else (including non-ASCII code points above U+007F) is emitted as its
# UTF-8 byte sequence. The JCS spec explicitly permits raw UTF-8 for
# characters outside the mandatory-escape set.
_ESCAPE_MAP = {
    0x22: r"\"",
    0x5C: r"\\",
    0x08: r"\b",
    0x0C: r"\f",
    0x0A: r"\n",
    0x0D: r"\r",
    0x09: r"\t",
}


def _encode_string(value: str) -> str:
    """Encode a JCS string: NFC-normalise, escape control chars, UTF-8.

    Output includes the surrounding quote characters.
    """
    normalised = unicodedata.normalize("NFC", value)
    parts: list[str] = ['"']
    for ch in normalised:
        cp = ord(ch)
        if cp in _ESCAPE_MAP:
            parts.append(_ESCAPE_MAP[cp])
        elif cp < 0x20:
            # Control characters require ``\uXXXX`` escapes.
            parts.append(f"\\u{cp:04x}")
        else:
            # BMP + supplementary characters emit as raw UTF-8. Python
            # str already carries them as Unicode; the outer .encode()
            # in :func:`dumps_jcs` writes them as UTF-8 bytes.
            parts.append(ch)
    parts.append('"')
    return "".join(parts)


def _check_bmp_only(key: str) -> None:
    """Refuse dict keys carrying supplementary-plane (non-BMP) code points.

    Python string sort is by Unicode code point; JCS specifies UTF-16
    code unit order. The two orderings differ for supplementary-plane
    characters (U+10000 and above, encoded as surrogate pairs in
    UTF-16). RACT's entire key vocabulary today is ASCII field names +
    BMP-only strings, so this branch never fires in practice. Refusing
    supplementary-plane keys converts the divergence from a silent
    ordering bug into a loud attest-time error; the v0.6 upgrade path
    is a proper UTF-16 sort key (Flagged gap tracked in
    ``_BUILD/ract_v0.5.1_external_review_response/module_03.md``).
    """
    for ch in key:
        if ord(ch) > 0xFFFF:
            raise CanonicalJSONError(
                f"Dict key {key!r} contains a supplementary-plane code point "
                f"(U+{ord(ch):04X}). BMP-only keys are supported in v0.5.1; "
                f"see module_03.md Flagged gaps for the UTF-16 sort upgrade."
            )
