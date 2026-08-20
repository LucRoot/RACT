"""Hypothesis property tests for the Historical Manifest Ledger (module_07).

Two properties:

- **Chain-invariant.** For any sequence of N appends of well-formed
  observations, :meth:`ManifestLedger.verify_chain` returns
  ``valid=True`` and ``tail_valid_count == N``.

- **Tamper-detection.** For any chain of at least 2 entries, mutating
  any middle entry's ``rootknot_run_id`` produces a chain that
  :meth:`verify_chain` marks broken at the FIRST index whose
  ``prev_ledger_hash`` no longer matches the actual hash of the
  mutated prior entry.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ract.canonical import dumps_jcs
from ract.security.manifest_ledger import (
    ManifestLedger,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


_digest_hex = st.builds(
    lambda i: hashlib.sha256(f"digest-{i}".encode("utf-8")).hexdigest(),
    st.integers(min_value=0, max_value=2**16),
)

_run_id = st.builds(
    lambda i: hashlib.sha256(f"run-{i}".encode("utf-8")).hexdigest()[:32],
    st.integers(min_value=0, max_value=2**16),
)

_sig = st.builds(
    lambda i: hashlib.sha512(f"sig-{i}".encode("utf-8")).digest(),
    st.integers(min_value=0, max_value=2**16),
)


@dataclass(frozen=True)
class _Observation:
    manifest_digest: str
    run_id: str
    sig: bytes


_obs = st.builds(
    lambda d, r, s: _Observation(manifest_digest=d, run_id=r, sig=s),
    _digest_hex,
    _run_id,
    _sig,
)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@given(observations=st.lists(_obs, min_size=1, max_size=8))
@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_verify_chain_always_valid_after_N_appends(
    tmp_path_factory: pytest.TempPathFactory,
    observations: list[_Observation],
) -> None:
    """Property: any well-formed append sequence verifies cleanly."""
    tmp = tmp_path_factory.mktemp("ledger")
    ledger = ManifestLedger(tmp / ".ract")
    seen: set[tuple[str, str]] = set()
    unique = 0
    for obs in observations:
        key = (obs.run_id, obs.manifest_digest)
        result = ledger.append(
            manifest_digest=obs.manifest_digest,
            rootknot_signature=obs.sig,
            rootknot_run_id=obs.run_id,
        )
        if key not in seen:
            unique += 1
            seen.add(key)
            assert result.duplicate is False
        else:
            assert result.duplicate is True
    verified = ledger.verify_chain()
    assert verified.valid is True
    assert verified.first_break_at is None
    assert verified.tail_valid_count == unique


@given(observations=st.lists(_obs, min_size=3, max_size=8, unique_by=lambda o: (o.run_id, o.manifest_digest)))
@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_middle_tamper_detected_at_next_entry(
    tmp_path_factory: pytest.TempPathFactory,
    observations: list[_Observation],
) -> None:
    """Property: mutating a middle entry breaks the chain at the NEXT entry."""
    tmp = tmp_path_factory.mktemp("ledger")
    ledger = ManifestLedger(tmp / ".ract")
    for obs in observations:
        ledger.append(
            manifest_digest=obs.manifest_digest,
            rootknot_signature=obs.sig,
            rootknot_run_id=obs.run_id,
        )
    entries = ledger.load()
    n = len(entries)
    if n < 2:
        pytest.skip("need >= 2 entries after dedup")
    # Mutate the middle entry (or the first non-tail entry).
    tamper_index = n // 2 if n > 2 else 0
    raw = ledger.ledger_path.read_bytes()
    body_lines = [ln for ln in raw.split(b"\n") if ln]
    entry = json.loads(body_lines[tamper_index])
    entry["rootknot_run_id"] = "9" * 32
    body_lines[tamper_index] = dumps_jcs(entry)
    ledger.ledger_path.write_bytes(b"\n".join(body_lines) + b"\n")

    result = ledger.verify_chain()
    if tamper_index == n - 1:
        # Mutating the last entry: no following entry to detect it, so
        # chain still verifies but the tail entry's content has drifted.
        # verify_chain does not re-check any per-entry invariant beyond
        # prev_ledger_hash, so this case is documented as a pass.
        assert result.valid is True
    else:
        assert result.valid is False
        assert result.first_break_at == tamper_index + 1
        assert result.tail_valid_count == tamper_index + 1


# RACT 0.5.1
