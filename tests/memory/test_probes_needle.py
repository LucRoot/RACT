"""Tests for :mod:`ract.memory.probes.needle`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pytest

from ract.memory.events import NullEventSink
from ract.memory.functions.testing import MockProvider
from ract.memory.probes.needle import NeedleProbe, NeedleProbeReport


# Subclass MockProvider (module_06 POST inbound constraint 2 — reuse
# the shipped mock rather than rolling a fresh stub) with a policy
# callback so tests can pin the recall pattern per (depth, size) pair.
@dataclass
class PolicyMockProvider(MockProvider):
    policy: Callable[[str, Any], bool] | None = None
    recorded_prompts: list[str] = field(default_factory=list)

    def send(self, prompt: str, declaration: Any) -> str:  # type: ignore[override]
        self.recorded_prompts.append(prompt)
        # Route the recording through MockProvider.send so the
        # call_log entry lands. Fallback returns "{}"; we replace it.
        super().send(prompt, declaration)
        if self.policy is None:
            return "not found"
        return "BLUE-42-ZULU" if self.policy(prompt, declaration) else "not found"


def _always_hit(_prompt: str, _decl: Any) -> bool:
    return True


def _always_miss(_prompt: str, _decl: Any) -> bool:
    return False


def _make_depth_policy(hit_depths: set[float]) -> Callable[[str, Any], bool]:
    probe = NeedleProbe()

    def policy(prompt: str, _decl: Any) -> bool:
        for depth in probe.DEPTHS:
            for size in probe.CONTEXT_SIZES:
                if prompt == probe.build_prompt(size, depth):
                    return depth in hit_depths
        return False

    return policy


def test_build_prompt_places_needle_and_question() -> None:
    probe = NeedleProbe()
    prompt = probe.build_prompt(size=100, depth=0.5)
    assert probe.NEEDLE in prompt
    assert probe.QUESTION in prompt


def test_build_prompt_length_matches_size_within_tolerance() -> None:
    probe = NeedleProbe()
    prompt = probe.build_prompt(size=200, depth=0.5)
    # Whitespace-token count should land at or just above the target
    # because the needle + question also carry tokens. The probe's
    # ``size`` is the filler size (as documented on build_prompt).
    word_count = len(prompt.split())
    assert word_count >= 200 - 1
    assert word_count <= 200 + len(probe.NEEDLE.split()) + len(probe.QUESTION.split())


def test_build_prompt_refuses_zero_size() -> None:
    probe = NeedleProbe()
    with pytest.raises(ValueError):
        probe.build_prompt(size=0, depth=0.5)


def test_build_prompt_refuses_out_of_range_depth() -> None:
    probe = NeedleProbe()
    with pytest.raises(ValueError):
        probe.build_prompt(size=100, depth=1.5)


def test_response_contains_needle_case_insensitive() -> None:
    probe = NeedleProbe()
    assert probe.response_contains_needle("The code is blue-42-zulu, over.")
    assert not probe.response_contains_needle("I do not know.")


def test_run_all_hit_reports_max_context_window() -> None:
    """Every depth hits at every size → usable_context_window = largest size."""
    probe = NeedleProbe()
    provider = PolicyMockProvider(policy=_always_hit)
    report = probe.run(provider)
    assert isinstance(report, NeedleProbeReport)
    assert report.usable_context_window == max(probe.CONTEXT_SIZES)
    for depth in probe.DEPTHS:
        for size in probe.CONTEXT_SIZES:
            assert report.recall_at_depth[depth][size] is True


def test_run_all_miss_reports_zero_context_window() -> None:
    probe = NeedleProbe()
    provider = PolicyMockProvider(policy=_always_miss)
    report = probe.run(provider)
    assert report.usable_context_window == 0


def test_run_cliff_detection_pins_window_to_last_size_where_all_depths_hit() -> None:
    """Module_08.md spec test: mock hits at depths [5, 25, 50], misses [75, 95].

    Because deep-depth misses occur at every size, the usable_context_window
    is zero — no size at which ALL depths recall.
    """
    probe = NeedleProbe()
    hits = {0.05, 0.25, 0.50}
    provider = PolicyMockProvider(policy=_make_depth_policy(hits))
    report = probe.run(provider)
    for size in probe.CONTEXT_SIZES:
        assert report.recall_at_depth[0.05][size] is True
        assert report.recall_at_depth[0.25][size] is True
        assert report.recall_at_depth[0.50][size] is True
        assert report.recall_at_depth[0.75][size] is False
        assert report.recall_at_depth[0.95][size] is False
    assert report.usable_context_window == 0


def test_run_emits_probe_evaluated_events() -> None:
    probe = NeedleProbe()
    provider = PolicyMockProvider(policy=_always_hit)
    sink = NullEventSink()
    probe.run(provider, sink=sink)
    kinds = [kind for kind, _ in sink.records]
    assert kinds
    assert all(kind == "probe.evaluated" for kind in kinds)
    # One event per (depth, size) pair.
    expected = len(probe.DEPTHS) * len(probe.CONTEXT_SIZES)
    assert len(sink.records) == expected


def test_run_records_prompts_on_provider() -> None:
    probe = NeedleProbe()
    provider = PolicyMockProvider(policy=_always_hit)
    probe.run(provider)
    expected = len(probe.DEPTHS) * len(probe.CONTEXT_SIZES)
    assert len(provider.recorded_prompts) == expected
    # Every recorded prompt is the exact deterministic construction.
    prompts = set(provider.recorded_prompts)
    for depth in probe.DEPTHS:
        for size in probe.CONTEXT_SIZES:
            assert probe.build_prompt(size, depth) in prompts


def test_report_is_frozen_dataclass() -> None:
    probe = NeedleProbe()
    provider = PolicyMockProvider(policy=_always_hit)
    report = probe.run(provider)
    with pytest.raises(Exception):
        report.usable_context_window = 12345  # type: ignore[misc]
