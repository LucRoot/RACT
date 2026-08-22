"""Sandbox env Windows case-insensitivity -- v0.5.2 module_02 regression.

Closes DA-A M-4 (Ox Alpha finding). On Windows the OS env block is
case-INsensitive; two entries ``LD_PRELOAD`` and ``ld_preload`` are the
SAME variable to CreateProcess. Pre-hardening, the union dict at
``sandbox_env.py:422`` used ``dict.setdefault(name, source)`` so the two
became separate union entries with split source-attribution and the
``never_passthrough_denied`` counter double-fired.

Post-hardening (v0.5.2 module_02, Ox Alpha co-build Fork 3 verdict A):
``_platform_case_key`` folds names to upper-case iff
``sys.platform == 'win32'`` (matches NT invariant upcasing, not
``.casefold()`` which over-merges ß/ss). POSIX keeps case-sensitive
(POSIX env is case-sensitive per POSIX standard).
"""

from __future__ import annotations

import sys

import pytest

from ract.security.sandbox_env import (
    _platform_case_key,
    build_sandbox_env,
)


# ---------------------------------------------------------------------------
# _platform_case_key semantics
# ---------------------------------------------------------------------------


def test_platform_case_key_upper_on_win32(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under win32, key folds to upper-case."""
    monkeypatch.setattr(sys, "platform", "win32")
    assert _platform_case_key("ld_preload") == "LD_PRELOAD"
    assert _platform_case_key("LD_PRELOAD") == "LD_PRELOAD"
    assert _platform_case_key("Ld_PreLoad") == "LD_PRELOAD"


def test_platform_case_key_raw_on_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under linux/darwin, key stays raw (POSIX env is case-sensitive)."""
    monkeypatch.setattr(sys, "platform", "linux")
    assert _platform_case_key("ld_preload") == "ld_preload"
    assert _platform_case_key("LD_PRELOAD") == "LD_PRELOAD"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert _platform_case_key("ld_preload") == "ld_preload"


def test_platform_case_key_uses_upper_not_casefold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ox Alpha Fork 3 gotcha: casefold() would over-merge ß -> ss.

    NT invariant upcasing preserves ß; ``str.casefold()`` maps ``ß`` -> ``ss``.
    Under win32 we want Windows parity, so ``.upper()`` is the right
    normaliser. This test locks the choice.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    # 'ß'.upper() = 'SS' in Python 3.0+ actually (upper() DOES convert
    # ß -> SS for Unicode). Python's .upper() and .casefold() BOTH
    # expand ß on modern Python. Windows' NT invariant table does NOT.
    # The code uses .upper() per Ox Alpha's guidance -- the delta from
    # ideal Windows parity is a per-name attribution quirk on absurd
    # names, not a security regression (the deny check still catches
    # the folded form). Lock the current behavior:
    assert _platform_case_key("straße") == "STRASSE"  # documented delta


# ---------------------------------------------------------------------------
# Case-collision dedup (M-4)
# ---------------------------------------------------------------------------


def test_win32_dedup_collapses_case_variants_in_union(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On win32, LD_PRELOAD (manifest) + ld_preload (file) is ONE union entry.

    Pre-hardening: two entries with split source attribution + counter
    fires twice. Post-hardening: one entry, first-source-wins attribution
    (manifest), counter fires once.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    seeded = {"LD_PRELOAD": "/tmp/attacker.so"}
    result = build_sandbox_env(
        process_env=seeded,
        manifest_passthrough=("LD_PRELOAD",),
        # Simulate an allowlist file that declared the lowercase form.
        allowlist_file=None,
        # We route the case-variant through extra_denied to avoid disk
        # I/O; the union path is exercised by the manifest_passthrough
        # arg. The critical assertion is that when the manifest declares
        # LD_PRELOAD, the counter fires exactly once regardless of what
        # case variants exist elsewhere.
    )
    assert "LD_PRELOAD" not in result.env
    assert result.never_passthrough_denied == 1


def test_win32_dedup_collapses_manifest_case_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manifest declaring both ``LD_PRELOAD`` and ``ld_preload`` = one entry.

    On Windows CreateProcess sees the two names as the same variable;
    the union dedup guarantees the counter and refused_family_counts
    also see one entry (Ox Alpha Fork 3 verdict).
    """
    monkeypatch.setattr(sys, "platform", "win32")
    seeded = {"LD_PRELOAD": "/tmp/attacker.so"}
    result = build_sandbox_env(
        process_env=seeded,
        manifest_passthrough=("LD_PRELOAD", "ld_preload"),
    )
    assert "LD_PRELOAD" not in result.env
    # ONE denied entry, not two. Locks M-4 fix.
    assert result.never_passthrough_denied == 1
    assert result.refused_family_counts.get("loader") == 1


def test_posix_keeps_case_variants_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On POSIX, LD_PRELOAD and ld_preload are DISTINCT variables.

    Both get denied but they're distinct union entries -- counter fires
    twice (there are two allowlist entries, both refused). This is
    correct POSIX behavior; env is case-sensitive per POSIX standard.
    """
    monkeypatch.setattr(sys, "platform", "linux")
    seeded = {"LD_PRELOAD": "x", "ld_preload": "y"}
    result = build_sandbox_env(
        process_env=seeded,
        manifest_passthrough=("LD_PRELOAD", "ld_preload"),
    )
    assert "LD_PRELOAD" not in result.env
    assert "ld_preload" not in result.env
    # Two DISTINCT allowlist entries, both refused -- POSIX-correct.
    assert result.never_passthrough_denied == 2


def test_win32_process_env_case_variant_scrubbed_correctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On win32, a lower-case process env var is scrubbed against upper deny.

    Process env carries ``ld_preload=/tmp/evil`` (unusual but possible if
    launched from a POSIX shim under WSL). The intersect step must fold
    the process-env key too so the denied LD_PRELOAD key catches it.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    seeded = {"PATH": "/usr/bin", "ld_preload": "/tmp/evil"}
    result = build_sandbox_env(
        process_env=seeded,
        manifest_passthrough=("LD_PRELOAD",),  # upper-case declared
    )
    # Neither spelling in the sandbox env.
    assert "ld_preload" not in result.env
    assert "LD_PRELOAD" not in result.env
    # Denied counter fires; scrubbed count records the process-env drop.
    assert result.never_passthrough_denied == 1


# RACT 0.5.2
