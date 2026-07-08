from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.observability_sink import ObservabilitySink, _ROOT_KNOT


def test_record_adds_event():
    sink = ObservabilitySink()
    event = {"type": "step_start", "payload": {"action": "write_file"}}
    sink.record(event)
    assert len(sink.get_events()) == 1
    assert sink.get_events()[0] == event


def test_record_ignores_root_knot():
    sink = ObservabilitySink()
    sink.record(_ROOT_KNOT)  # should be ignored, no error
    assert len(sink.get_events()) == 0


def test_clear_removes_all():
    sink = ObservabilitySink()
    sink.record({"a": 1})
    sink.clear()
    assert len(sink.get_events()) == 0


def test_root_knot_is_defined():
    import rootact.observability_sink as mod

    assert hasattr(mod, "_ROOT_KNOT")
    assert mod._ROOT_KNOT is _ROOT_KNOT
