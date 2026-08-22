"""Regression -- module_03 SP amendment fixes.

v0.5.2 hardening module_03 SP amendment. Locks the three SP DEFECT
verdicts:

- **Q1 (Ox Alpha DEFECT):** ``current_identity`` on POSIX must
  return ``None`` for a definitively-dead pid, not the
  ``(pid, 0)`` fallback. Pre-amendment this caused false
  ``pid_reuse_detected`` telemetry on every normal
  dispose-after-exit.
- **Q2 (Ox Alpha + cross-family converged DEFECT):** the
  per-signal identity check must distinguish MATCH / GONE /
  MISMATCH. Pre-amendment GONE was treated as refuse-signal
  which reintroduced the DA-A F-4 class bug (parent exits during
  grace loop -> killpg skipped -> orphan leak). Post-amendment
  ``_identity_verdict`` returns tri-state and callers fire
  killpg on MATCH or GONE, refuse only on MISMATCH.
- **Q6 (cross-family DEFECT):** ``orphan_reaped`` event ``count``
  field must reflect TOTAL live descendants pre-cap, not the
  truncated list length. Pre-amendment a leak-of-200 reported
  ``count=32``.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from ract.executor import process_group as pg
from ract.executor.process_group import (
    ProcessGroupHandle,
    _identity_verdict,
    _IDENTITY_GONE,
    _IDENTITY_MATCH,
    _IDENTITY_MISMATCH,
    _emit_orphan_reaped,
)
from ract.executor.process_identity import (
    ProcessIdentity,
    current_identity,
)


# ---------------------------------------------------------------------------
# Q1 (Ox Alpha DEFECT) -- current_identity returns None on dead POSIX pid
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_current_identity_returns_none_for_dead_posix_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POSIX: dead pid -> None, not (pid, 0). Ox Alpha Q1 DEFECT fix.

    Simulates POSIX (even on Windows CI) by forcing the platform
    branch + patching the existence probe to return False.
    """
    # Patch the identity module directly for the POSIX branch.
    import ract.executor.process_identity as pid_mod

    monkeypatch.setattr(pid_mod, "_IS_WINDOWS", False)
    monkeypatch.setattr(
        pid_mod, "_read_posix_starttime_ns", lambda pid: None
    )
    monkeypatch.setattr(
        pid_mod, "_read_posix_ctime_ns_fallback", lambda pid: None
    )
    # Dead pid probe: os.kill(pid, 0) -> ProcessLookupError.
    monkeypatch.setattr(pid_mod, "_posix_pid_exists", lambda pid: False)

    result = pid_mod.current_identity(99999)
    assert result is None, (
        "dead POSIX pid must return None -- not the (pid, 0) fallback. "
        "Pre-amendment this returned ProcessIdentity(pid=99999, 0) "
        "and downstream same_process(stored, (pid,0)) -> False -> "
        "false pid_reuse_detected on every dispose-after-exit."
    )


@pytest.mark.timeout(30)
def test_current_identity_returns_fallback_for_live_pid_without_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POSIX live-but-un-guardable pid: (pid, 0) fallback preserved.

    macOS/BSD case: pid EXISTS but no /proc source available.
    """
    import ract.executor.process_identity as pid_mod

    monkeypatch.setattr(pid_mod, "_IS_WINDOWS", False)
    monkeypatch.setattr(
        pid_mod, "_read_posix_starttime_ns", lambda pid: None
    )
    monkeypatch.setattr(
        pid_mod, "_read_posix_ctime_ns_fallback", lambda pid: None
    )
    # Live pid probe: returns True.
    monkeypatch.setattr(pid_mod, "_posix_pid_exists", lambda pid: True)

    result = pid_mod.current_identity(12345)
    assert result is not None
    assert result.pid == 12345
    assert result.creation_time_ns == 0, (
        "un-guardable-but-live pid must return (pid, 0) fallback "
        "so macOS operators can still use subprocess-backed subagents"
    )


# ---------------------------------------------------------------------------
# Q2 (Ox Alpha + cross-family DEFECT) -- tri-state _identity_verdict
# ---------------------------------------------------------------------------


def test_identity_verdict_returns_match_on_agreeing_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = ProcessIdentity(pid=1000, creation_time_ns=555)
    monkeypatch.setattr(
        pg, "current_identity", lambda pid: ProcessIdentity(1000, 555)
    )
    handle = ProcessGroupHandle(
        popen=None,  # type: ignore[arg-type]
        pgid=1000,
        identity=stored,
    )
    assert _identity_verdict(handle) == _IDENTITY_MATCH


def test_identity_verdict_returns_gone_when_current_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GONE verdict lets callers proceed with pgid/JobObject reap.

    Ox Alpha Q2 DEFECT fix: pre-amendment ``_reverify_ok`` returned
    False for None current identity, causing killpg to be skipped
    and reintroducing the DA-A F-4 class bug.
    """
    stored = ProcessIdentity(pid=1000, creation_time_ns=555)
    monkeypatch.setattr(pg, "current_identity", lambda pid: None)
    handle = ProcessGroupHandle(
        popen=None,  # type: ignore[arg-type]
        pgid=1000,
        identity=stored,
    )
    assert _identity_verdict(handle) == _IDENTITY_GONE, (
        "GONE (current=None) MUST be distinct from MISMATCH -- "
        "callers proceed with group primitives on GONE"
    )


def test_identity_verdict_returns_mismatch_and_emits_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = ProcessIdentity(pid=1000, creation_time_ns=555)
    reused = ProcessIdentity(pid=1000, creation_time_ns=999)
    monkeypatch.setattr(pg, "current_identity", lambda pid: reused)

    events_captured: list[tuple[str, dict]] = []

    def _fake_emit(kind: str, payload: dict) -> None:
        events_captured.append((kind, dict(payload)))

    import ract.trace.sink as sink_mod

    monkeypatch.setattr(sink_mod, "emit", _fake_emit)

    handle = ProcessGroupHandle(
        popen=None,  # type: ignore[arg-type]
        pgid=1000,
        identity=stored,
    )
    assert _identity_verdict(handle) == _IDENTITY_MISMATCH
    # Event fires exactly once.
    reuse_events = [
        p
        for (k, p) in events_captured
        if k == "substrate.subagent.pid_reuse_detected"
    ]
    assert len(reuse_events) == 1


def test_identity_verdict_returns_match_on_unguardable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No stored identity -> MATCH (bare-pid trust; caller proceeds)."""
    handle = ProcessGroupHandle(
        popen=None,  # type: ignore[arg-type]
        pgid=1000,
        identity=None,
    )
    assert _identity_verdict(handle) == _IDENTITY_MATCH


# ---------------------------------------------------------------------------
# Q6 (cross-family DEFECT) -- orphan_reaped count reflects TRUE total
# ---------------------------------------------------------------------------


def test_orphan_reaped_event_count_reflects_true_total_pre_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """count field on orphan_reaped event = total observed, not truncated.

    Cross-family Q6 DEFECT fix: pre-amendment a leak-of-200
    reported ``count=32`` (the len of the capped list). Now
    ``count=200`` + ``pids=[first 32]`` + ``pids_truncated=True``.
    """
    events_captured: list[tuple[str, dict]] = []

    def _fake_emit(kind: str, payload: dict) -> None:
        events_captured.append((kind, dict(payload)))

    import ract.trace.sink as sink_mod

    monkeypatch.setattr(sink_mod, "emit", _fake_emit)

    total = 200
    capped_pids = list(range(10000, 10032))  # 32 entries
    _emit_orphan_reaped(total, capped_pids)

    orphan_events = [
        p
        for (k, p) in events_captured
        if k == "substrate.subagent.orphan_reaped"
    ]
    assert len(orphan_events) == 1
    payload = orphan_events[0]
    assert payload["count"] == 200, (
        "count MUST reflect the TRUE total observed, not the "
        "truncated list length -- Q6 DEFECT fix"
    )
    assert len(payload["pids"]) == 32
    assert payload["pids_truncated"] is True


def test_orphan_reaped_event_untruncated_when_below_cap() -> None:
    """When total <= cap, pids_truncated is False."""
    events_captured: list[tuple[str, dict]] = []

    def _fake_emit(kind: str, payload: dict) -> None:
        events_captured.append((kind, dict(payload)))

    import ract.trace.sink as sink_mod
    from unittest.mock import patch

    with patch.object(sink_mod, "emit", _fake_emit):
        _emit_orphan_reaped(3, [111, 222, 333])

    orphan_events = [
        p
        for (k, p) in events_captured
        if k == "substrate.subagent.orphan_reaped"
    ]
    assert len(orphan_events) == 1
    payload = orphan_events[0]
    assert payload["count"] == 3
    assert payload["pids_truncated"] is False


# RACT 0.5.2
