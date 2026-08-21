"""Integration: sycophancy_v2 fires from the loop callback.

Contract (v0.5.1 wiring module_07, Lens E AL-E-01 closure):

- ``LoopController._run_sycophancy_v2_check`` extracts the primary
  response text from a :class:`LoopIteration` and invokes
  :func:`ract.antilazy.sycophancy_v2.classify`.
- On a null-op agreement response the classifier's ``emit_event()``
  fires ``whisperer.contract_violation`` on the trace channel.
- With no response text (Plan-only iteration) the check is a no-op.
- The check never raises — a trace-sink or import failure inside the
  helper does not blow up the loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch


@dataclass
class _StepResult:
    content: str = ""


@dataclass
class _ExecReport:
    step_results: list[_StepResult] = field(default_factory=list)


class _FakeIteration:
    def __init__(self, intent: str, response: str) -> None:
        self.intent = intent
        self.report = _ExecReport(step_results=[_StepResult(content=response)])


def _make_controller(tmp_path: Path):
    """Build a LoopController with minimal wiring for the check helper."""
    from ract.loop_controller import LoopController

    cfg = tmp_path / "ract.yaml"
    cfg.write_text("providers: {}\n", encoding="utf-8")
    return LoopController(cfg)


def test_extract_response_text_handles_empty_report(tmp_path):
    controller = _make_controller(tmp_path)

    class _NoReport:
        intent = "x"
        report = None

    assert controller._extract_response_text(_NoReport()) == ""


def test_extract_response_text_concatenates_multi_step(tmp_path):
    controller = _make_controller(tmp_path)
    it = _FakeIteration("intent", "primary reply")
    it.report.step_results.append(_StepResult(content="follow-up"))
    text = controller._extract_response_text(it)
    assert "primary reply" in text
    assert "follow-up" in text


def test_sycophantic_response_emits_whisperer_contract_violation(tmp_path):
    """A null-op agreement response fires whisperer.contract_violation."""
    controller = _make_controller(tmp_path)
    # Intent asks a real question; response is a null-op agreement.
    request = (
        "Implement a function that sums a list of integers, guarding "
        "against non-integer entries by raising TypeError."
    )
    response = (
        "You're absolutely right. Indeed, well said. That is a great "
        "approach. I completely agree with what you have proposed."
    )
    it = _FakeIteration(request, response)

    events: list = []

    def _fake_emit(name, payload, **kwargs):
        events.append((name, payload))

    with patch("ract.trace.sink.emit", _fake_emit):
        controller._run_sycophancy_v2_check(it)

    kinds = [name for (name, _) in events]
    assert "whisperer.contract_violation" in kinds, (
        f"expected whisperer.contract_violation event, got {kinds!r}"
    )


def test_check_is_noop_when_response_empty(tmp_path):
    controller = _make_controller(tmp_path)

    class _EmptyIt:
        intent = "x"
        report = _ExecReport(step_results=[])

    events: list = []

    def _fake_emit(name, payload, **kwargs):
        events.append((name, payload))

    with patch("ract.trace.sink.emit", _fake_emit):
        controller._run_sycophancy_v2_check(_EmptyIt())

    # No response text -> the classifier never runs -> no event.
    assert not events


def test_check_never_raises_on_classifier_error(tmp_path):
    controller = _make_controller(tmp_path)
    it = _FakeIteration("intent", "response")
    fake_classify = MagicMock(side_effect=RuntimeError("boom"))
    with patch(
        "ract.antilazy.sycophancy_v2.classify",
        fake_classify,
    ):
        # Must not raise.
        controller._run_sycophancy_v2_check(it)
