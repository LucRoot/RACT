"""Tests for :mod:`ract.memory.probes.adherence`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pytest

from ract.memory.events import NullEventSink
from ract.memory.functions.testing import MockProvider
from ract.memory.probes.adherence import AdherenceProbe, AdherenceProbeReport


@dataclass
class PolicyMockProvider(MockProvider):
    policy: Callable[[str, Any], bool] | None = None
    recorded_prompts: list[str] = field(default_factory=list)

    def send(self, prompt: str, declaration: Any) -> str:  # type: ignore[override]
        self.recorded_prompts.append(prompt)
        super().send(prompt, declaration)
        if self.policy is None:
            return "4"
        return "CROW: 4" if self.policy(prompt, declaration) else "4"


def _size_leq(threshold: int) -> Callable[[str, Any], bool]:
    probe = AdherenceProbe()
    size_by_prompt = {probe.build_prompt(size): size for size in probe.CONTEXT_SIZES}

    def policy(prompt: str, _decl: Any) -> bool:
        size = size_by_prompt.get(prompt)
        if size is None:
            return False
        return size <= threshold

    return policy


def test_build_prompt_places_instruction_and_question() -> None:
    probe = AdherenceProbe()
    prompt = probe.build_prompt(size=200)
    assert probe.INSTRUCTION in prompt
    assert probe.QUESTION in prompt
    # Instruction is seated FIRST.
    assert prompt.lstrip().startswith(probe.INSTRUCTION)


def test_response_honors_requires_exact_prefix() -> None:
    probe = AdherenceProbe()
    assert probe.response_honors_instruction("CROW: 4")
    # Leading whitespace tolerated.
    assert probe.response_honors_instruction("  CROW: hi")
    # Lowercase prefix is a miss (instruction pinned the casing).
    assert not probe.response_honors_instruction("crow: 4")
    assert not probe.response_honors_instruction("Answer: 4")
    assert not probe.response_honors_instruction("")


def test_run_all_hit_reports_max_bound() -> None:
    probe = AdherenceProbe()
    provider = PolicyMockProvider(policy=lambda p, d: True)
    report = probe.run(provider)
    assert isinstance(report, AdherenceProbeReport)
    assert report.persistence_bound == max(probe.CONTEXT_SIZES)


def test_run_module_08_spec_scenario_identifies_below_4k_misses_above() -> None:
    """Module_08.md spec: hits at sizes <= 4000, misses at >= 8000 → bound == 4000."""
    probe = AdherenceProbe()
    provider = PolicyMockProvider(policy=_size_leq(4000))
    report = probe.run(provider)
    assert report.instruction_persistence_at_size[2000] is True
    assert report.instruction_persistence_at_size[4000] is True
    assert report.instruction_persistence_at_size[8000] is False
    assert report.instruction_persistence_at_size[16000] is False
    assert report.persistence_bound == 4000


def test_run_all_miss_reports_zero_bound() -> None:
    probe = AdherenceProbe()
    provider = PolicyMockProvider(policy=lambda p, d: False)
    report = probe.run(provider)
    assert report.persistence_bound == 0


def test_run_emits_probe_evaluated_events() -> None:
    probe = AdherenceProbe()
    provider = PolicyMockProvider(policy=lambda p, d: True)
    sink = NullEventSink()
    probe.run(provider, sink=sink)
    assert len(sink.records) == len(probe.CONTEXT_SIZES)


def test_report_is_frozen_dataclass() -> None:
    probe = AdherenceProbe()
    provider = PolicyMockProvider(policy=lambda p, d: True)
    report = probe.run(provider)
    with pytest.raises(Exception):
        report.persistence_bound = 999999  # type: ignore[misc]
