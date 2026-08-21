"""Tests for :mod:`ract.memory.probes.scheduler`."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from ract.memory.functions.testing import MockProvider
from ract.memory.probes.adherence import AdherenceProbe
from ract.memory.probes.coherence import CoherenceProbe
from ract.memory.probes.needle import NeedleProbe
from ract.memory.probes.scheduler import (
    CAPABILITY_RECORD_PATH,
    CAPABILITY_SCHEMA_VERSION,
    ModelCapability,
    ProbeReports,
    ProbeScheduler,
    read_capability_record,
    reduce_to_capability,
    run_all_probes,
    write_capability_record,
)


@dataclass
class AlwaysHitProvider(MockProvider):
    """Provider that satisfies every probe (needle / coherence / adherence)."""

    def send(self, prompt: str, declaration: Any) -> str:  # type: ignore[override]
        super().send(prompt, declaration)
        return "CROW: BLUE-42-ZULU tuesday wednesday"


@dataclass
class AlwaysMissProvider(MockProvider):
    """Provider that fails every probe."""

    def send(self, prompt: str, declaration: Any) -> str:  # type: ignore[override]
        super().send(prompt, declaration)
        return "no response"


def test_run_all_probes_returns_three_reports() -> None:
    provider = AlwaysHitProvider()
    reports = run_all_probes(provider)
    assert isinstance(reports, ProbeReports)
    assert reports.needle.usable_context_window == max(NeedleProbe.CONTEXT_SIZES)
    assert reports.coherence.reasoning_quality_bound == max(
        CoherenceProbe.CONTEXT_SIZES
    )
    assert reports.adherence.persistence_bound == max(AdherenceProbe.CONTEXT_SIZES)


def test_probe_scheduler_run_once_uses_injected_probes() -> None:
    small_needle = NeedleProbe()
    small_needle.CONTEXT_SIZES = (100,)  # type: ignore[misc]
    small_needle.DEPTHS = (0.5,)  # type: ignore[misc]
    scheduler = ProbeScheduler(needle_probe=small_needle)
    provider = AlwaysHitProvider()
    reports = scheduler.run_once(provider)
    assert reports.needle.usable_context_window == 100


def test_reduce_to_capability_uses_report_fields() -> None:
    provider = AlwaysHitProvider()
    reports = run_all_probes(provider)
    capability = reduce_to_capability(reports)
    assert capability.usable_context_window == reports.needle.usable_context_window
    assert (
        capability.reasoning_quality_bound == reports.coherence.reasoning_quality_bound
    )
    assert capability.persistence_bound == reports.adherence.persistence_bound


def test_write_and_read_capability_record_roundtrip(tmp_path: Path) -> None:
    provider = AlwaysHitProvider()
    reports = run_all_probes(provider)
    target = write_capability_record(reports, tmp_path)
    assert target == tmp_path / CAPABILITY_RECORD_PATH
    assert target.is_file()
    loaded = read_capability_record(tmp_path)
    assert loaded is not None
    assert loaded.usable_context_window == reports.needle.usable_context_window
    assert loaded.reasoning_quality_bound == reports.coherence.reasoning_quality_bound
    assert loaded.persistence_bound == reports.adherence.persistence_bound
    assert loaded.schema_version == CAPABILITY_SCHEMA_VERSION


def test_read_capability_record_missing_returns_none(tmp_path: Path) -> None:
    assert read_capability_record(tmp_path) is None


def test_read_capability_record_malformed_json_raises(tmp_path: Path) -> None:
    target = tmp_path / CAPABILITY_RECORD_PATH
    target.parent.mkdir(parents=True)
    target.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        read_capability_record(tmp_path)


def test_read_capability_record_wrong_schema_version_raises(tmp_path: Path) -> None:
    target = tmp_path / CAPABILITY_RECORD_PATH
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps(
            {
                "schema_version": 99,
                "usable_context_window": 1,
                "reasoning_quality_bound": 1,
                "persistence_bound": 1,
                "recorded_at": 0,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported schema_version"):
        read_capability_record(tmp_path)


def test_read_capability_record_missing_field_raises(tmp_path: Path) -> None:
    target = tmp_path / CAPABILITY_RECORD_PATH
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps({"schema_version": CAPABILITY_SCHEMA_VERSION}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required field"):
        read_capability_record(tmp_path)


def test_write_capability_record_creates_parent_dirs(tmp_path: Path) -> None:
    reports = run_all_probes(AlwaysHitProvider())
    target = write_capability_record(reports, tmp_path)
    assert target.parent.is_dir()


def test_write_capability_record_atomic_no_leftover_tmp(tmp_path: Path) -> None:
    reports = run_all_probes(AlwaysHitProvider())
    write_capability_record(reports, tmp_path)
    # v0.5.1 wiring module_10 (Lens A C2): state dir unified on ``.ract/``.
    leftover = list((tmp_path / ".ract" / "probes").glob("*.tmp"))
    assert leftover == []


def test_write_capability_record_overwrites_prior(tmp_path: Path) -> None:
    reports_1 = run_all_probes(AlwaysHitProvider())
    write_capability_record(reports_1, tmp_path)
    reports_2 = run_all_probes(AlwaysMissProvider())
    write_capability_record(reports_2, tmp_path)
    loaded = read_capability_record(tmp_path)
    assert loaded is not None
    assert loaded.usable_context_window == 0
    assert loaded.reasoning_quality_bound == 0
    assert loaded.persistence_bound == 0


def test_model_capability_is_frozen_dataclass() -> None:
    capability = ModelCapability(
        usable_context_window=1,
        reasoning_quality_bound=2,
        persistence_bound=3,
        recorded_at=4,
    )
    with pytest.raises(Exception):
        capability.usable_context_window = 99  # type: ignore[misc]
