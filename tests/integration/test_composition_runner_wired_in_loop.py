"""LoopController wires CompositionRunner + ProbeScheduler.

v0.5.1 wiring module_08 (Lens E MEM-E-04) closure. These primitives
were previously packaged in :mod:`ract.memory.composition_runner` and
:mod:`ract.memory.probes.scheduler` but no loop_controller caller
invoked them. Module_08 adds four optional constructor arguments and
two dispatch methods.

Wiring shape (opt-in): default construction (no probes / no runner)
is a no-op so v0.5.0 callers stay compatible; injecting the
dependencies activates the wire without changing any other loop
behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ract.loop_controller import LoopController


def _minimal_config(tmp_path: Path) -> Path:
    """Return a valid config path so LoopController.__init__ succeeds."""
    cfg = tmp_path / "ract.yaml"
    cfg.write_text("version: 1\n", encoding="utf-8")
    return cfg


class _CapturingScheduler:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def run_once(self, provider: Any) -> Any:
        self.calls.append(provider)
        # Return a shape :func:`write_capability_record` accepts.
        from ract.memory.probes.adherence import AdherenceProbeReport
        from ract.memory.probes.coherence import CoherenceProbeReport
        from ract.memory.probes.needle import NeedleProbeReport
        from ract.memory.probes.scheduler import ProbeReports

        return ProbeReports(
            needle=NeedleProbeReport(
                recall_at_depth={},
                usable_context_window=8000,
            ),
            coherence=CoherenceProbeReport(
                identified_at_size={},
                reasoning_quality_bound=8,
            ),
            adherence=AdherenceProbeReport(
                instruction_persistence_at_size={},
                persistence_bound=4,
            ),
        )


class _CapturingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def run_playbook(
        self,
        spec: Any,
        request: str,
        repo_root: Any,
        provider: Any,
        indexes: Any,
        **kwargs: Any,
    ) -> str:
        self.calls.append((spec, request, repo_root, provider, indexes, kwargs))
        return "ok"


def test_default_construction_leaves_wireins_opt_in(tmp_path: Path) -> None:
    ctrl = LoopController(_minimal_config(tmp_path))
    assert ctrl.composition_runner is None
    assert ctrl.probe_scheduler is None
    assert ctrl.probe_provider is None
    assert ctrl.memory_indexes is None
    assert ctrl.memory_root is None


def test_probe_scheduler_fires_at_run_start(tmp_path: Path) -> None:
    """When both scheduler + provider are set, run() invokes run_once."""
    scheduler = _CapturingScheduler()
    provider = object()
    ctrl = LoopController(
        _minimal_config(tmp_path),
        probe_scheduler=scheduler,
        probe_provider=provider,
        memory_root=tmp_path,
    )
    # Call the wire helper directly so we do not have to stand up a
    # full acceptance suite + planner just to exercise a boot path.
    ctrl._run_probe_scheduler_at_start()
    assert scheduler.calls == [provider]
    # Capability record must land at the standard path.
    assert (tmp_path / ".rack" / "probes" / "capability.json").is_file()


def test_probe_scheduler_wire_is_noop_without_provider(tmp_path: Path) -> None:
    scheduler = _CapturingScheduler()
    ctrl = LoopController(
        _minimal_config(tmp_path),
        probe_scheduler=scheduler,
        probe_provider=None,
        memory_root=tmp_path,
    )
    ctrl._run_probe_scheduler_at_start()
    assert scheduler.calls == []


def test_probe_scheduler_runs_at_most_once_per_run(tmp_path: Path) -> None:
    scheduler = _CapturingScheduler()
    provider = object()
    ctrl = LoopController(
        _minimal_config(tmp_path),
        probe_scheduler=scheduler,
        probe_provider=provider,
        memory_root=tmp_path,
    )
    ctrl._run_probe_scheduler_at_start()
    ctrl._run_probe_scheduler_at_start()  # second call is a no-op
    assert len(scheduler.calls) == 1


def test_composition_runner_dispatches_when_wired(tmp_path: Path) -> None:
    runner = _CapturingRunner()
    indexes = object()
    provider = object()
    ctrl = LoopController(
        _minimal_config(tmp_path),
        composition_runner=runner,
        memory_indexes=indexes,
        memory_root=tmp_path,
    )
    result = ctrl._run_composed_retrieval(
        spec="playbook-spec-sentinel",
        request="hello",
        provider=provider,
    )
    assert result == "ok"
    assert len(runner.calls) == 1
    spec, request, repo_root, prov, idx, _ = runner.calls[0]
    assert spec == "playbook-spec-sentinel"
    assert request == "hello"
    assert Path(repo_root) == Path(tmp_path)
    assert prov is provider
    assert idx is indexes


def test_composition_runner_noop_when_absent(tmp_path: Path) -> None:
    ctrl = LoopController(_minimal_config(tmp_path))
    result = ctrl._run_composed_retrieval(
        spec=None, request="x", provider=None
    )
    assert result is None


def test_composition_runner_noop_when_indexes_absent(tmp_path: Path) -> None:
    runner = _CapturingRunner()
    ctrl = LoopController(
        _minimal_config(tmp_path),
        composition_runner=runner,
    )
    result = ctrl._run_composed_retrieval(
        spec=None, request="x", provider=None
    )
    assert result is None
    assert runner.calls == []
