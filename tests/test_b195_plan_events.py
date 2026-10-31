"""B-195 (a): an edited plan is announced again in the shape of ``plan.proposed``.

The edit re-emitted ``plan.proposed`` with the payload of
``plan.approval_requested`` (``plan_hash`` and steps), so the assumption line
vanished from the summary and ``planned`` was missing.
"""

from __future__ import annotations

from tests.test_plan_approval_review_points import PLAN, _harness, _run


def test_the_edited_plan_keeps_assumption_confidence_and_planned(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    harness = _harness(tmp_path, PLAN, "aaa", "bbb")
    _, events, _, _ = _run(
        harness,
        monkeypatch,
        ["edit 1", "Create a, written as the file a.txt with one line", "approve"],
    )
    proposed = [d for k, d in events if k == "plan.proposed"]
    assert len(proposed) >= 2
    first, again = proposed[0], proposed[-1]
    for field in ("assumption", "confidence", "planned"):
        assert again[field] == first[field], field
    assert "plan_hash" not in again
    assert again["steps"][0]["action"] != first["steps"][0]["action"]  # the edited step


def test_an_agent_step_has_no_target_and_the_hash_ignores_the_shown_words() -> None:
    # B-195 (b): the prose "(the files its tools change)" was the agent step's
    # target on one path, so it reached plan_hash and result.plan[].file.
    from ract import plan_gate
    from ract.approval_callback import _plan_steps
    from ract.manager import Plan, Step
    from ract.ui.plan_approval_view import AGENT_TARGET_TEXT, Step as PlanStep, screen_lines

    plan = Plan(
        assumption="a", confidence=1.0,
        steps=[Step(action="fix the test", provider_hint="", expected_artifact="", agent=True)],
    )
    steps = _plan_steps(plan)
    assert steps[0].target is None and steps[0].agent
    payload = plan_gate.approval_requested_payload(steps)
    assert payload["steps"][0]["target"] is None
    plain = [PlanStep(n=1, action="fix the test")]
    assert plan_gate.plan_hash(steps) == plan_gate.plan_hash(plain)
    assert any(AGENT_TARGET_TEXT in line for line in screen_lines(steps, 80))


def test_an_interrupted_turn_says_so_and_not_that_git_is_missing() -> None:
    # B-195 (c): changed None on an interrupted turn printed "not a git repository".
    import io

    from ract.session_events import EventStream
    from ract.session_render import PlainRenderer

    for outcome, expected in (
        ("interrupted", "changed: not known (the turn was interrupted)"),
        ("done", "changed: not tracked here (not a git repository)"),
    ):
        out = io.StringIO()
        stream = EventStream(session="s-b195")
        stream.subscribe(PlainRenderer(out.write, width=80))
        stream.emit(
            "turn.finished",
            {"outcome": outcome, "verdict": "Stopped.", "changed": None,
             "verification": {"status": "not-run", "runs": []}},
            turn=1,
        )
        assert expected in out.getvalue(), out.getvalue()


def test_mode_changed_carries_the_real_tier_3_state() -> None:
    # B-195 (d): /mode emitted tier3 "off" whatever tier 3 was.
    from ract.session_events import EventStream, SessionEvent
    from tests.test_repl import _session

    for grant_state, session_mode, expected in (
        ("off", "ask", "off"),
        ("suspended", "ask", "suspended"),
        ("ask", "allowlist", "allowlist"),
        ("allowlist", "ask", "ask"),
    ):
        session, _calls, _console = _session()
        seen: list[SessionEvent] = []
        stream = EventStream(session="s-b195d")
        stream.subscribe(seen.append)
        session._events = stream
        session._tier3 = grant_state
        session._tier3_mode = session_mode
        session.handle("/mode plan")
        changed = [e.data for e in seen if e.kind == "mode.changed"]
        assert changed and changed[-1]["tier3"] == expected, (grant_state, changed)


def test_a_turn_started_from_the_queue_says_queued(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # B-195 (e): turn.started.queued was never true.
    from ract import session_turn
    from ract.session_events import EventStream
    from tests.test_repl import _session

    seen: list[bool] = []

    def fake_run_turn(stream, request, *, turn, cancel, queued=False):  # type: ignore[no-untyped-def]
        seen.append(queued)
        return 0

    monkeypatch.setattr(session_turn, "run_turn", fake_run_turn)
    session, _calls, _console = _session()
    session._events = EventStream(session="s-b195e")
    session._from_queue = True
    session._event_turn("fix it", dry=True)
    session._from_queue = False
    session._event_turn("fix it again", dry=True)
    assert seen == [True, False]
