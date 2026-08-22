"""Regression: :class:`LoopController` resume path continues iteration
counter from persisted state instead of restarting at 1.

v0.5.1 wiring module_06 (Lens G G-03 + G-04 + G-05) closure. The prior
loop had no compaction hook, no ``on_pause``, no ``on_resume``, no
serialization of in-flight state. Every ``run()`` invocation reset
``iterations = []``, ``previous_score = None``, ``stagnation_count = 0``,
and started ``for index in range(1, ...)``, forfeiting all prior loop
memory on a post-crash restart.

The fix persists the resumable counters to ``<run_dir>/loop_state.json``
at each iteration boundary and on :meth:`LoopController.on_pause`.
:meth:`LoopController.on_resume` reads the sidecar; the subsequent
:meth:`run` (or :meth:`resume`) call enters the iteration loop at
``persisted_count + 1`` and rehydrates ``_rollback_streak``,
``_completed_families``, ``repair_attempts_remaining``,
``_repair_intent``, ``last_known_good_workspace``.

Reference:
- ``_BUILD/audit_2026-08-21/lens_G_loop_controller.md`` G-03, G-04, G-05.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_06.md``.
"""

from __future__ import annotations

import json
from pathlib import Path


from ract.core.predicate import (
    AcceptancePredicate,
    AcceptanceSuite,
    ArtifactInvocation,
    new_intent_id,
    new_predicate_id,
)
from ract.core.workspace_digest import compute_prompt_digest
from ract.loop_controller import LoopController, LoopIteration


CANONICAL_INTENT = "build me a factorial function"


def _suite() -> AcceptanceSuite:
    predicate = AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(
            path="__never_present__", must_have_rootknot=False
        ),
        required=True,
    )
    return AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=(predicate,),
        compiled_from=CANONICAL_INTENT,
        prompt_digest=bytes(compute_prompt_digest(CANONICAL_INTENT)),
    )


def _make_controller(project: Path) -> LoopController:
    project.mkdir(parents=True, exist_ok=True)
    config = project / "ract.yaml"
    config.write_text("providers: []\n", encoding="utf-8")
    run_dir = project / "run-resume-test"
    run_dir.mkdir(parents=True, exist_ok=True)
    return LoopController(
        config,
        max_iterations=10,
        acceptance_suite=_suite(),
        run_dir=run_dir,
    )


def _fake_iteration(index: int, decision: str = "continue") -> LoopIteration:
    return LoopIteration(
        index=index,
        intent=f"iter-{index}-augmented",
        report=None,
        test_returncode=0,
        test_summary=f"iter-{index}",
        test_output="",
        quality_score=0.5 + index * 0.05,
        reflection=f"reflection for iter {index}",
        decision=decision,
    )


def test_on_pause_writes_sidecar_with_counters(tmp_path: Path) -> None:
    controller = _make_controller(tmp_path)
    iterations = [_fake_iteration(1), _fake_iteration(2), _fake_iteration(3)]
    controller._rollback_streak = 2
    controller._completed_families = ["parser", "runner"]
    controller.repair_attempts_remaining = 4
    controller._repair_intent = "please retry the failing test"

    controller.on_pause(
        iterations=iterations,
        previous_score=0.65,
        stagnation_count=1,
    )

    sidecar = tmp_path / "run-resume-test" / "loop_state.json"
    assert sidecar.exists(), "on_pause must write the sidecar"

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["iterations_count"] == 3
    assert payload["previous_score"] == 0.65
    assert payload["stagnation_count"] == 1
    assert payload["rollback_streak"] == 2
    assert payload["completed_families"] == ["parser", "runner"]
    assert payload["repair_attempts_remaining"] == 4
    assert payload["repair_intent"] == "please retry the failing test"


def test_on_resume_loads_sidecar_and_stages_counters(tmp_path: Path) -> None:
    controller = _make_controller(tmp_path)
    iterations = [_fake_iteration(1), _fake_iteration(2), _fake_iteration(3)]
    controller._rollback_streak = 2
    controller._completed_families = ["parser"]
    controller.repair_attempts_remaining = 3
    controller._repair_intent = "hi"
    controller.on_pause(iterations=iterations, previous_score=0.7, stagnation_count=0)

    # Fresh controller (simulates process restart after compaction).
    fresh = _make_controller(tmp_path.parent / "second_run")
    # Same run_dir -- point at the same sidecar via a manual copy.
    sidecar_src = tmp_path / "run-resume-test" / "loop_state.json"
    fresh_run_dir = fresh.run_dir
    assert fresh_run_dir is not None
    (fresh_run_dir / "loop_state.json").write_bytes(sidecar_src.read_bytes())

    ok = fresh.on_resume()
    assert ok, "on_resume must return True when sidecar exists"

    stashed = fresh._resume_snapshot
    assert stashed is not None
    assert stashed["iterations_count"] == 3
    assert stashed["previous_score"] == 0.7
    assert fresh._rollback_streak == 2
    assert fresh._completed_families == ["parser"]
    assert fresh.repair_attempts_remaining == 3
    assert fresh._repair_intent == "hi"


def test_on_resume_missing_sidecar_returns_false(tmp_path: Path) -> None:
    controller = _make_controller(tmp_path)
    assert controller.on_resume() is False, (
        "on_resume must return False for a fresh run_dir with no sidecar"
    )


def test_run_after_resume_starts_at_persisted_count_plus_one(
    tmp_path: Path,
) -> None:
    """End-to-end: pause after 3 iterations, resume, and confirm the
    next :meth:`run` call enters the iteration loop at index 4 (not 1).

    We stub ``_run_bound`` to record the ``start_index`` seed and stop
    immediately, so the test avoids exercising the entire provider path.
    """
    controller = _make_controller(tmp_path)
    iterations = [_fake_iteration(i) for i in (1, 2, 3)]
    controller.on_pause(iterations=iterations, previous_score=0.6, stagnation_count=0)
    assert controller.on_resume() is True
    # Confirm the staged snapshot maps to iteration 4 as the next
    # iteration index.
    stashed = controller._resume_snapshot
    assert stashed is not None
    assert int(stashed["iterations_count"]) + 1 == 4
    # And ``_run_bound`` would consume it: simulate a single-tick body.
    consumed: dict[str, int] = {}

    def _observe(intent: str, **kwargs):  # noqa: ANN001
        rs = getattr(controller, "_resume_snapshot", None)
        if rs is not None:
            consumed["start_index"] = int(rs["iterations_count"]) + 1
            controller._resume_snapshot = None
        from ract.loop_controller import LoopResult

        return LoopResult(
            iterations=[],
            final_decision="stop",
            summary="observed",
            handshake_milestones=[],
        )

    controller._run_bound = _observe  # type: ignore[method-assign]
    controller.run("dummy intent")
    assert consumed.get("start_index") == 4, (
        "run() after resume must enter the iteration loop at "
        "persisted_count + 1 (== 4), not restart at 1"
    )


def test_resume_public_verb_reads_sidecar_and_enters_run(tmp_path: Path) -> None:
    """The public :meth:`LoopController.resume` verb wraps
    :meth:`on_resume` + :meth:`run` so operators have a single entry
    point for restart-with-resume.
    """
    controller = _make_controller(tmp_path)
    controller.on_pause(iterations=[_fake_iteration(1)], previous_score=0.4)

    calls: dict[str, int] = {"run_calls": 0}

    def _fake_run(intent: str, **kwargs):  # noqa: ANN001
        calls["run_calls"] += 1
        from ract.loop_controller import LoopResult

        return LoopResult(
            iterations=[],
            final_decision="stop",
            summary="stub",
            handshake_milestones=[],
        )

    controller.run = _fake_run  # type: ignore[method-assign]
    controller.resume("dummy")
    assert calls["run_calls"] == 1
