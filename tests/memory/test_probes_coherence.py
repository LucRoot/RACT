"""Tests for :mod:`ract.memory.probes.coherence`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pytest

from ract.memory.events import NullEventSink
from ract.memory.functions.testing import MockProvider
from ract.memory.probes.coherence import CoherenceProbe, CoherenceProbeReport


@dataclass
class PolicyMockProvider(MockProvider):
    policy: Callable[[str, Any], bool] | None = None
    recorded_prompts: list[str] = field(default_factory=list)

    def send(self, prompt: str, declaration: Any) -> str:  # type: ignore[override]
        self.recorded_prompts.append(prompt)
        super().send(prompt, declaration)
        if self.policy is None:
            return ""
        if self.policy(prompt, declaration):
            return "The passage mentions both Tuesday and Wednesday for the meeting."
        return "I found no inconsistency."


def _size_leq(threshold: int) -> Callable[[str, Any], bool]:
    """Policy: succeed for sizes <= threshold; fail for larger."""
    probe = CoherenceProbe()
    size_by_prompt = {probe.build_prompt(size): size for size in probe.CONTEXT_SIZES}

    def policy(prompt: str, _decl: Any) -> bool:
        size = size_by_prompt.get(prompt)
        if size is None:
            return False
        return size <= threshold

    return policy


def test_build_prompt_places_both_statements_and_question() -> None:
    probe = CoherenceProbe()
    prompt = probe.build_prompt(size=200)
    assert probe.STATEMENT_A in prompt
    assert probe.STATEMENT_B in prompt
    assert probe.QUESTION in prompt


def test_build_prompt_refuses_zero_size() -> None:
    probe = CoherenceProbe()
    with pytest.raises(ValueError):
        probe.build_prompt(size=0)


def test_response_identifies_requires_both_tokens() -> None:
    probe = CoherenceProbe()
    assert probe.response_identifies_inconsistency(
        "The document says Tuesday but later says Wednesday."
    )
    assert not probe.response_identifies_inconsistency("Only Tuesday is mentioned.")
    assert not probe.response_identifies_inconsistency("Only wednesday exists.")


def test_run_all_hit_reports_max_bound() -> None:
    probe = CoherenceProbe()
    provider = PolicyMockProvider(policy=lambda p, d: True)
    report = probe.run(provider)
    assert isinstance(report, CoherenceProbeReport)
    assert report.reasoning_quality_bound == max(probe.CONTEXT_SIZES)


def test_run_module_08_spec_scenario_identifies_below_4k_misses_above() -> None:
    """Module_08.md spec: hits at sizes <= 4000, misses at >= 8000 → bound == 4000."""
    probe = CoherenceProbe()
    provider = PolicyMockProvider(policy=_size_leq(4000))
    report = probe.run(provider)
    assert report.identified_at_size[2000] is True
    assert report.identified_at_size[4000] is True
    assert report.identified_at_size[8000] is False
    assert report.identified_at_size[16000] is False
    assert report.reasoning_quality_bound == 4000


def test_run_all_miss_reports_zero_bound() -> None:
    probe = CoherenceProbe()
    provider = PolicyMockProvider(policy=lambda p, d: False)
    report = probe.run(provider)
    assert report.reasoning_quality_bound == 0


def test_run_emits_probe_evaluated_events() -> None:
    probe = CoherenceProbe()
    provider = PolicyMockProvider(policy=lambda p, d: True)
    sink = NullEventSink()
    probe.run(provider, sink=sink)
    assert len(sink.records) == len(probe.CONTEXT_SIZES)
    assert all(kind == "probe.evaluated" for kind, _ in sink.records)


def test_report_is_frozen_dataclass() -> None:
    probe = CoherenceProbe()
    provider = PolicyMockProvider(policy=lambda p, d: True)
    report = probe.run(provider)
    with pytest.raises(Exception):
        report.reasoning_quality_bound = 999999  # type: ignore[misc]
