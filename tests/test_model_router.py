from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import pytest

from rootact.model_router import (
    FakeCapableBackend,
    FakeFastBackend,
    ModelBackend,
    ModelRouter,
    _ROOT_KNOT,
)


def test_root_knot_is_module_sentinel():
    assert _ROOT_KNOT is not None
    assert type(_ROOT_KNOT) is object


def test_model_backend_process():
    backend = ModelBackend("test", {"task_types": ["general"]})
    assert backend.process("general") == "processed by test"


def test_router_selects_exact_match():
    fast = FakeFastBackend()
    capable = FakeCapableBackend()
    router = ModelRouter([fast, capable])
    selected = router.route("boilerplate", "low")
    assert selected.name == "fast"


def test_router_falls_back_to_most_capable():
    fast = FakeFastBackend()
    capable = FakeCapableBackend()
    router = ModelRouter([fast, capable])
    selected = router.route("unknown", "high")
    assert selected.name == "capable"


def test_route_fallback_raises_when_empty():
    router = ModelRouter()
    with pytest.raises(RuntimeError, match="No backends registered"):
        router.route_fallback("anything", "low")


def test_supported_task_types():
    fast = FakeFastBackend()
    capable = FakeCapableBackend()
    router = ModelRouter([fast, capable])
    assert "boilerplate" in router.supported_task_types()
    assert "diagnose" in router.supported_task_types()


# RACT 0.1.0 - Initial Public Release
