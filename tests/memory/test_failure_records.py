"""Tests for :mod:`ract.memory.failure_records`."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ract.memory.composition_runner import PhaseRecord
from ract.memory.failure_records import (
    APPLIED_NARROWINGS_PATH,
    FAILURE_RECORDS_PATH,
    AggregateReport,
    FailureRecord,
    NarrowingProposal,
    StaleReferenceError,
    aggregate,
    append_applied_narrowing,
    failure_from_phase_record,
    read_all,
    rewrite_records_atomic,
    validate_proposal_against_live_value,
    write,
)


def _make_record(
    *,
    function: str = "edit",
    failure_type: str = "budget_exceeded",
    resolution: str = "level_1_format_downgrade",
    input_tokens: int = 8000,
    timestamp: int | None = None,
) -> FailureRecord:
    return FailureRecord(
        function=function,
        input_token_count=input_tokens,
        output_token_count=0,
        failure_type=failure_type,  # type: ignore[arg-type]
        resolution_level_reached=resolution,  # type: ignore[arg-type]
        timestamp=timestamp if timestamp is not None else int(time.time()),
    )


def test_failure_record_construction_and_validation() -> None:
    rec = _make_record()
    assert rec.function == "edit"
    assert rec.failure_type == "budget_exceeded"


def test_failure_record_refuses_unknown_failure_type() -> None:
    with pytest.raises(ValueError, match="not in"):
        FailureRecord(
            function="edit",
            input_token_count=1,
            output_token_count=1,
            failure_type="unknown_kind",  # type: ignore[arg-type]
            resolution_level_reached="none",
            timestamp=1,
        )


def test_failure_record_refuses_unknown_resolution_level() -> None:
    with pytest.raises(ValueError, match="not in"):
        FailureRecord(
            function="edit",
            input_token_count=1,
            output_token_count=1,
            failure_type="budget_exceeded",
            resolution_level_reached="level_5_shrug",  # type: ignore[arg-type]
            timestamp=1,
        )


def test_failure_record_refuses_negative_token_counts() -> None:
    with pytest.raises(ValueError):
        FailureRecord(
            function="edit",
            input_token_count=-1,
            output_token_count=0,
            failure_type="budget_exceeded",
            resolution_level_reached="none",
            timestamp=1,
        )


def test_failure_record_refuses_empty_function() -> None:
    with pytest.raises(ValueError):
        FailureRecord(
            function="",
            input_token_count=0,
            output_token_count=0,
            failure_type="budget_exceeded",
            resolution_level_reached="none",
            timestamp=1,
        )


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    rec = _make_record()
    target = write(rec, tmp_path)
    assert target == tmp_path / FAILURE_RECORDS_PATH
    loaded = read_all(tmp_path)
    assert len(loaded) == 1
    assert loaded[0] == rec


def test_read_all_missing_returns_empty(tmp_path: Path) -> None:
    assert read_all(tmp_path) == []


def test_read_all_malformed_line_raises(tmp_path: Path) -> None:
    target = tmp_path / FAILURE_RECORDS_PATH
    target.parent.mkdir(parents=True)
    target.write_text("not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed JSON"):
        read_all(tmp_path)


def test_write_appends_across_calls(tmp_path: Path) -> None:
    for i in range(3):
        write(_make_record(input_tokens=1000 + i), tmp_path)
    loaded = read_all(tmp_path)
    assert len(loaded) == 3
    assert [rec.input_token_count for rec in loaded] == [1000, 1001, 1002]


def test_narrowing_proposal_refuses_widening() -> None:
    with pytest.raises(ValueError, match="refuses widening"):
        NarrowingProposal(
            function="edit",
            field_name="input_target",
            new_value=9000,
            reference_current_value=8000,
            reason="test",
        )


def test_narrowing_proposal_allows_equal_or_less() -> None:
    # Equal is allowed (no-op narrowing is defensible).
    prop = NarrowingProposal(
        function="edit",
        field_name="input_target",
        new_value=8000,
        reference_current_value=8000,
        reason="noop",
    )
    assert prop.new_value == 8000


def test_aggregate_produces_no_proposals_below_threshold(tmp_path: Path) -> None:
    now = 1_000_000
    for _ in range(2):  # threshold is 3
        write(_make_record(timestamp=now - 1000), tmp_path)
    report = aggregate(tmp_path, now=now)
    assert isinstance(report, AggregateReport)
    assert report.proposals == ()
    assert report.total_records_considered == 2


def test_aggregate_produces_narrowing_proposal_at_threshold(tmp_path: Path) -> None:
    """Three budget_exceeded on 'edit' at input=8000 → narrows input_target to 6400."""
    now = 1_000_000
    for i in range(3):
        write(
            _make_record(input_tokens=8000, timestamp=now - (100 * (i + 1))),
            tmp_path,
        )
    report = aggregate(tmp_path, now=now)
    assert len(report.proposals) == 1
    proposal = report.proposals[0]
    assert proposal.function == "edit"
    assert proposal.field_name == "input_target"
    # 8000 * 0.8 = 6400
    assert proposal.new_value == 6400
    assert proposal.reference_current_value == 8000
    # Always-narrowing invariant.
    assert proposal.new_value <= proposal.reference_current_value


def test_aggregate_respects_current_budgets_map(tmp_path: Path) -> None:
    """Explicit current_budgets overrides the observed-input reference."""
    now = 1_000_000
    for i in range(3):
        write(_make_record(input_tokens=8000, timestamp=now - i), tmp_path)
    report = aggregate(
        tmp_path,
        now=now,
        current_budgets={("edit", "input_target"): 10000},
    )
    proposal = report.proposals[0]
    assert proposal.reference_current_value == 10000
    assert proposal.new_value == 8000  # 10000 * 0.8


def test_aggregate_excludes_records_outside_window(tmp_path: Path) -> None:
    now = 100_000_000
    old = now - 30 * 86400  # 30 days ago
    for _ in range(5):
        write(_make_record(timestamp=old), tmp_path)
    report = aggregate(tmp_path, now=now, window_days=7)
    assert report.total_records_considered == 0
    assert report.proposals == ()


def test_aggregate_never_widens_across_multiple_calls(tmp_path: Path) -> None:
    now = 1_000_000
    for _ in range(3):
        write(_make_record(input_tokens=8000, timestamp=now), tmp_path)
    report_1 = aggregate(tmp_path, now=now)
    report_2 = aggregate(tmp_path, now=now)
    assert report_1.proposals == report_2.proposals


def test_aggregate_counts_by_function_and_type(tmp_path: Path) -> None:
    now = 1_000_000
    write(_make_record(function="edit", timestamp=now), tmp_path)
    write(_make_record(function="edit", timestamp=now), tmp_path)
    write(
        _make_record(function="plan", failure_type="phase_raised", timestamp=now),
        tmp_path,
    )
    report = aggregate(tmp_path, now=now)
    assert report.counts_by_function_and_type == {
        "edit": {"budget_exceeded": 2},
        "plan": {"phase_raised": 1},
    }


def test_failure_from_phase_record_returns_none_when_ok() -> None:
    phase = PhaseRecord(
        phase_name="edit",
        function="edit",
        duration_ms=10,
        outcome="ok",
    )
    assert failure_from_phase_record(phase) is None


def test_failure_from_phase_record_returns_record_when_raised() -> None:
    phase = PhaseRecord(
        phase_name="edit",
        function="edit",
        duration_ms=10,
        outcome="raised",
    )
    record = failure_from_phase_record(phase, now=1234)
    assert record is not None
    assert record.function == "edit"
    assert record.failure_type == "phase_raised"
    assert record.timestamp == 1234


def test_failure_from_phase_record_classifies_reproduce_note() -> None:
    phase = PhaseRecord(
        phase_name="reproduce",
        function="reproduce",
        duration_ms=1,
        outcome="raised",
        notes=("reproduce: command exited zero: bug did not reproduce",),
    )
    record = failure_from_phase_record(phase)
    assert record is not None
    assert record.failure_type == "unconfirmed_bug"


def test_failure_from_phase_record_classifies_oversize_target() -> None:
    phase = PhaseRecord(
        phase_name="edit",
        function="edit",
        duration_ms=1,
        outcome="raised",
        notes=("oversize target function detected",),
    )
    record = failure_from_phase_record(phase)
    assert record is not None
    assert record.failure_type == "oversize_target"


def test_append_applied_narrowing_writes_audit_line(tmp_path: Path) -> None:
    proposal = NarrowingProposal(
        function="edit",
        field_name="input_target",
        new_value=6400,
        reference_current_value=8000,
        reason="3 failures",
    )
    target = append_applied_narrowing(
        proposal, tmp_path, applied_at=42, operator_note="ok"
    )
    assert target == tmp_path / APPLIED_NARROWINGS_PATH
    text = target.read_text(encoding="utf-8")
    assert '"function": "edit"' in text
    assert '"new": 6400' in text
    assert '"old": 8000' in text
    assert '"operator_note": "ok"' in text


def test_validate_proposal_against_live_value_ok_when_narrowing() -> None:
    proposal = NarrowingProposal(
        function="edit",
        field_name="input_target",
        new_value=6400,
        reference_current_value=8000,
        reason="test",
    )
    # Live value equals stale reference: safe.
    validate_proposal_against_live_value(proposal, 8000)
    # Live value smaller than stale reference but proposal still narrows.
    validate_proposal_against_live_value(proposal, 6400)


def test_validate_proposal_against_live_value_refuses_stale_reference() -> None:
    """SP Q4 Orthogonal 3: stale current_budgets could bypass the always-narrowing invariant."""
    # Aggregator was fed current_budgets={('edit', 'input_target'): 8000}
    # but live budget is actually 5000. The proposal narrows to 6400 vs
    # the stale reference — but applying against live 5000 would widen.
    proposal = NarrowingProposal(
        function="edit",
        field_name="input_target",
        new_value=6400,
        reference_current_value=8000,
        reason="stale test",
    )
    with pytest.raises(StaleReferenceError):
        validate_proposal_against_live_value(proposal, 5000)


def test_append_applied_narrowing_refuses_stale_live_value(tmp_path: Path) -> None:
    proposal = NarrowingProposal(
        function="edit",
        field_name="input_target",
        new_value=6400,
        reference_current_value=8000,
        reason="stale test",
    )
    with pytest.raises(StaleReferenceError):
        append_applied_narrowing(proposal, tmp_path, live_current_value=5000)


def test_append_applied_narrowing_accepts_live_value_when_safe(tmp_path: Path) -> None:
    proposal = NarrowingProposal(
        function="edit",
        field_name="input_target",
        new_value=6400,
        reference_current_value=8000,
        reason="safe",
    )
    target = append_applied_narrowing(proposal, tmp_path, live_current_value=7000)
    assert target.is_file()


def test_rewrite_records_atomic_replaces_content(tmp_path: Path) -> None:
    write(_make_record(input_tokens=1), tmp_path)
    write(_make_record(input_tokens=2), tmp_path)
    # Keep only the second.
    surviving = [read_all(tmp_path)[1]]
    rewrite_records_atomic(surviving, tmp_path)
    reloaded = read_all(tmp_path)
    assert len(reloaded) == 1
    assert reloaded[0].input_token_count == 2
    # v0.5.1 wiring module_10 (Lens A C2): state dir unified on ``.ract/``.
    leftover = list((tmp_path / ".ract" / "failures").glob("*.tmp"))
    assert leftover == []
