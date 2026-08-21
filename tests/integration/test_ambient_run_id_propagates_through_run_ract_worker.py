"""Regression: ambient ``run_id`` bound at ``LoopController.run()``
entry propagates INTO the :meth:`_run_with_timeout` worker thread.

v0.5.1 wiring module_06 (Lens G G-01) closure. Prior to this module,
:meth:`_run_with_timeout` submitted ``run_ract`` to a bare
:class:`ThreadPoolExecutor`, so any subsystem that consulted
:func:`ract.runtime.get_current_run_id` inside the worker saw
``None`` -- fabricating fragmented defaults and re-introducing the
DeepSeek REVIEW_2 criticism 1 pathology that module_06 (Pipeline A')
was written to eliminate.

The fix wraps the submit in :func:`ract.runtime.run_with_ambient`.
This test binds a known ``run_id`` around a ``LoopController`` call
chain that reaches ``_run_with_timeout`` and asserts the worker
observes the bound value (via a stubbed ``run_ract``).

Reference:
- ``_BUILD/audit_2026-08-21/lens_G_loop_controller.md`` G-01.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_06.md``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ract.loop_controller import LoopController
from ract.rooted import Rooted
from ract.runtime import bind_run_id, get_current_run_id


def _make_controller(project: Path) -> LoopController:
    config = project / "ract.yaml"
    config.write_text("providers: []\n", encoding="utf-8")
    return LoopController(config, max_iterations=1)


def test_worker_thread_sees_bound_ambient_run_id(tmp_path: Path) -> None:
    """Bind a specific run_id in the caller context; the ``run_ract``
    stub called inside the pool worker MUST observe the same value via
    :func:`get_current_run_id`.
    """
    controller = _make_controller(tmp_path)
    observed: dict[str, str | None] = {"in_worker": None}

    def _stub_run_ract(*args, **kwargs):
        observed["in_worker"] = get_current_run_id()
        return Rooted(
            value=None,
            assumption="stub",
            confidence=1.0,
            provenance=["stub"],
            error="stub_stop",
        )

    bound_run_id = "aa" * 16  # 32-hex placeholder
    with bind_run_id(bound_run_id):
        assert get_current_run_id() == bound_run_id
        with patch("ract.loop_controller.run_ract", _stub_run_ract):
            result = controller._run_with_timeout("hello")
        # The stub returned a Rooted with an error -- ensure our stub
        # actually ran.
        assert result.error == "stub_stop"

    assert observed["in_worker"] == bound_run_id, (
        "Bare ThreadPoolExecutor.submit lost the ambient run_id. "
        "The submit must wrap the callable with run_with_ambient() so "
        "the worker inherits the caller's ContextVar snapshot "
        "(Lens G G-01)."
    )


def test_worker_thread_sees_none_when_no_ambient_bound(tmp_path: Path) -> None:
    """Complement: when no ``bind_run_id`` scope is active, the worker
    observes ``None`` (backward-compat sanity -- ``run_with_ambient``
    is safe with an empty context).
    """
    controller = _make_controller(tmp_path)
    observed: dict[str, str | None] = {"in_worker": "SENTINEL"}

    def _stub(*args, **kwargs):
        observed["in_worker"] = get_current_run_id()
        return Rooted(
            value=None,
            assumption="stub",
            confidence=1.0,
            provenance=["stub"],
            error="stub_stop",
        )

    with patch("ract.loop_controller.run_ract", _stub):
        controller._run_with_timeout("hello")
    assert observed["in_worker"] is None
