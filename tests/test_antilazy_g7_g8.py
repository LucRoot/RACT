"""Tests for ALM Gate G7 (companion red team) and Gate G8 (effort reconciliation).

ALM module_04. Seven baseline tests + guards for the Second Pass
adversarial questions + the trivial-rate-ceiling addition that closes
module_01's flagged gap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from ract.antilazy.companion import (
    CompanionConfig,
    CompanionProviderCollisionError,
    CompanionRedTeamReport,
    CounterexampleFinding,
    enforce_different_provider,
    run_companion,
)
from ract.antilazy.effort import (
    EffortActual,
    EffortEstimate,
    _extract_keywords,
    estimate_effort,
    measure_actual_effort,
    reconcile_effort,
    suspicion_prompt_text,
)
from ract.antilazy.holdout import (
    DEFAULT_TRIVIAL_RATE_CEILING,
    HoldoutCompilationRecord,
    TrivialRateCeilingExceededError,
    enforce_trivial_rate_ceiling,
)
from ract.antilazy.patchdiff import Hunk, Patch
from ract.core.loop import WorkspaceSnapshot
from ract.providers.gate import (
    DEFAULT_ANTI_LAZY_CONFORMANCE_THRESHOLD,
    GateConfig,
    check_provider_gate,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class _StubProvider:
    """Bare-bones Provider protocol satisfier."""

    name: str
    response_shape: str = "structured_outputs"

    def send_planned_step_request(self, **_kw):  # pragma: no cover - stub
        return "{}"


@dataclass
class _SpyAdapter:
    """CompanionAdapter that records what it was passed."""

    provider_name: str
    proposals: tuple[CounterexampleFinding, ...] = field(default_factory=tuple)
    seen_intent: str = ""
    seen_diff: object = None
    seen_visible: object = None

    def propose_counterexamples(self, *, intent, diff, visible_suite):
        self.seen_intent = intent
        self.seen_diff = diff
        self.seen_visible = visible_suite
        return self.proposals


@dataclass
class _RecordingRunner:
    """CounterexampleRunner that returns pre/post pass verdicts."""

    verdict: tuple[bool, bool]

    def run(self, finding, *, pre_change_workspace, post_change_workspace):
        return self.verdict


def _make_visible_suite():
    """Minimal AcceptanceSuite for tests."""
    from ract.core.predicate import (
        AcceptancePredicate,
        AcceptanceSuite,
        PytestInvocation,
        new_intent_id,
        new_predicate_id,
    )

    predicate = AcceptancePredicate(
        id=new_predicate_id(),
        kind="test",
        invocation=PytestInvocation(selector="tests/test_x.py"),
        required=True,
    )
    return AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=(predicate,),
        coverage_gate=0.0,
        compiled_from="stub",
        compiler_version="0.4.0",
    )


def _make_patch(added_lines: tuple[str, ...] = ("def foo(): return 1",)) -> Patch:
    return Patch(
        hunks=(
            Hunk(
                path="src/mod.py",
                added_lines=added_lines,
                removed_lines=(),
                start_line=1,
            ),
        )
    )


# ---------------------------------------------------------------------------
# Test 1 — companion receives visible only, not held-out
# ---------------------------------------------------------------------------


def test_companion_receives_visible_only_not_held_out():
    """The adapter must never see the held-out suite or the trace."""
    primary = _StubProvider(name="prov_primary")
    companion_provider = _StubProvider(name="prov_companion")
    adapter = _SpyAdapter(provider_name=companion_provider.name)
    config = CompanionConfig(provider=companion_provider)
    diff = _make_patch()
    visible = _make_visible_suite()

    report = run_companion(
        intent="fix the bug",
        diff=diff,
        visible_suite=visible,
        config=config,
        adapter=adapter,
        primary=primary,
        recent_history=(),
    )

    assert adapter.seen_intent == "fix the bug"
    assert adapter.seen_diff is diff
    # The adapter must receive the VISIBLE suite, not a DualAcceptanceSuite
    # (there is no ``held_out`` attribute reachable through what it saw).
    assert adapter.seen_visible is visible
    assert not hasattr(adapter.seen_visible, "held_out")
    assert isinstance(report, CompanionRedTeamReport)


# ---------------------------------------------------------------------------
# Test 2 — different-provider constraint enforced
# ---------------------------------------------------------------------------


def test_companion_different_provider_enforced():
    """A companion that matches the primary raises the collision error."""
    primary = _StubProvider(name="prov_shared")
    companion = _StubProvider(name="prov_shared")
    with pytest.raises(CompanionProviderCollisionError):
        enforce_different_provider(primary, companion, ())


def test_first_step_empty_history_still_guards_primary_equals_companion():
    """Second Pass Q1: empty history still refuses primary==companion."""
    primary = _StubProvider(name="prov_shared")
    companion = _StubProvider(name="prov_shared")
    with pytest.raises(CompanionProviderCollisionError):
        enforce_different_provider(primary, companion, recent_history=())


def test_single_provider_advisory_bypasses_check():
    """Lateral chain branch D: advisory mode bypasses the collision guard."""
    primary = _StubProvider(name="prov_shared")
    companion = _StubProvider(name="prov_shared")
    # Should not raise:
    enforce_different_provider(
        primary,
        companion,
        recent_history=(),
        allow_same_provider=True,
    )


# ---------------------------------------------------------------------------
# Test 3 — surviving counterexample emits violation and blocks COMPLETE
# ---------------------------------------------------------------------------


def test_surviving_counterexample_emits_violation_and_blocks_complete():
    """A finding that passes pre-change and fails post-change survives."""
    primary = _StubProvider(name="prov_primary")
    companion = _StubProvider(name="prov_companion")
    finding = CounterexampleFinding(
        test_id="cx_off_by_one",
        test_source="def test(): assert foo(1) == 1",
        description="off-by-one on the boundary",
        pre_change_pass=False,  # will be overridden by runner
        post_change_pass=True,
    )
    adapter = _SpyAdapter(
        provider_name=companion.name, proposals=(finding,)
    )
    # Runner says: passes pre-change, fails post-change (a surviving
    # counterexample).
    runner = _RecordingRunner(verdict=(True, False))
    report = run_companion(
        intent="fix the boundary",
        diff=_make_patch(),
        visible_suite=_make_visible_suite(),
        config=CompanionConfig(provider=companion),
        adapter=adapter,
        runner=runner,
        pre_change_workspace={},
        post_change_workspace={},
        primary=primary,
    )
    survivors = report.surviving_findings()
    assert len(survivors) == 1
    assert survivors[0].test_id == "cx_off_by_one"
    assert report.counterexamples_that_broke_claim == 1


# ---------------------------------------------------------------------------
# Test 4 — effort estimate is deterministic
# ---------------------------------------------------------------------------


def test_effort_estimate_is_deterministic():
    """Two calls with the same inputs return identical output."""
    intent = "refactor the authentication module to use a session store"
    ws = WorkspaceSnapshot(
        files={
            "src/auth/session.py": "def login(): pass",
            "src/auth/token.py": "def issue(): pass",
            "src/auth/user.py": "def get_user(): pass",
            "tests/test_auth.py": "def test_login(): assert True",
            "README.md": "auth module",
        }
    )
    e1 = estimate_effort(intent, ws)
    e2 = estimate_effort(intent, ws)
    assert e1 == e2
    # And no randomness across a third call for good measure.
    e3 = estimate_effort(intent, ws)
    assert e2 == e3


# ---------------------------------------------------------------------------
# Test 5 — realized below tau_effort triggers suspicion prompt
# ---------------------------------------------------------------------------


def test_realized_below_tau_effort_triggers_suspicion_prompt():
    """ratio['symbols_modified']=0.1 below tau=0.3 fires an anomaly."""
    estimate = EffortEstimate(
        files_touched_expected=10,
        symbols_modified_expected=10,
        tests_added_or_updated_expected=5,
        lines_changed_expected=100,
        estimate_source="heuristic",
    )
    actual = EffortActual(
        files_touched_realized=10,
        symbols_modified_realized=1,  # 0.1 ratio, below 0.3
        tests_added_or_updated_realized=5,
        lines_changed_realized=100,
    )
    recon = reconcile_effort(estimate, actual, tau_effort=0.3)
    assert "symbols_modified" in recon.anomalies
    text = suspicion_prompt_text(recon)
    assert "EFFORT RECONCILIATION" in text
    assert "symbols_modified" in text


# ---------------------------------------------------------------------------
# Test 6 — companion matrix regenerates idempotently
# ---------------------------------------------------------------------------


def test_companion_matrix_regenerates_idempotent(tmp_path: Path):
    """Two regen calls on the same inputs produce byte-identical output."""
    from evals.leaderboard.update_companion_matrix import (
        regenerate_companion_matrix,
    )

    results_root = tmp_path / "results"
    results_root.mkdir()
    for name, al_score, sc_score in (
        ("openai-adapter", 0.85, 0.98),
        ("anthropic-adapter", 0.82, 0.96),
        ("google-adapter", 0.80, 0.95),
    ):
        (results_root / f"{name}-2026-07-26.json").write_text(
            json.dumps(
                {
                    "provider": name,
                    "timestamp": "2026-07-26T00:00:00+00:00",
                    "categories": {
                        "schema_compliance": {"score": sc_score},
                        "tool_discipline": {"score": 0.99},
                        "refusal_fidelity": {"score": 1.0},
                        "anti_lazy": {"score": al_score},
                    },
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    output = tmp_path / "COMPANION_MATRIX.md"
    changed_1, rows_1 = regenerate_companion_matrix(
        results_root=results_root, output_path=output
    )
    assert changed_1 is True
    assert len(rows_1) == 3
    content_1 = output.read_bytes()
    changed_2, rows_2 = regenerate_companion_matrix(
        results_root=results_root, output_path=output
    )
    assert changed_2 is False
    assert len(rows_2) == 3
    assert output.read_bytes() == content_1
    # DoD leaf (c) — at least three primary-companion pairs land.
    assert content_1.decode("utf-8").count("Eligible pairs") == 1
    # Each of the three providers should see two eligible companions
    # (different-family from itself).
    text = content_1.decode("utf-8")
    for pname in ("openai-adapter", "anthropic-adapter", "google-adapter"):
        assert pname in text


# ---------------------------------------------------------------------------
# Test 7 — provider below anti-lazy conformance refused at registration
# ---------------------------------------------------------------------------


def test_provider_below_anti_lazy_conformance_refused_at_registration(
    tmp_path: Path,
):
    """A provider whose anti_lazy score is below 0.7 fails the gate."""
    results_root = tmp_path / "results"
    results_root.mkdir()
    report = {
        "provider": "slow-provider",
        "timestamp": "2026-07-26T00:00:00+00:00",
        "categories": {
            "schema_compliance": {"score": 0.99},
            "tool_discipline": {"score": 1.0},
            "refusal_fidelity": {"score": 1.0},
            "anti_lazy": {"score": 0.50},
        },
    }
    (results_root / "slow-provider-2026-07-26.json").write_text(
        json.dumps(report, sort_keys=True, indent=2), encoding="utf-8"
    )
    outcome = check_provider_gate("slow-provider", results_root=results_root)
    assert outcome.admitted is False
    assert "anti_lazy" in outcome.reason


def test_missing_anti_lazy_category_does_not_refuse_older_reports(
    tmp_path: Path,
):
    """Reports produced before ALM shipped omit the category; still admit."""
    results_root = tmp_path / "results"
    results_root.mkdir()
    report = {
        "provider": "legacy-provider",
        "timestamp": "2026-07-26T00:00:00+00:00",
        "categories": {
            "schema_compliance": {"score": 0.99},
            "tool_discipline": {"score": 1.0},
            "refusal_fidelity": {"score": 1.0},
        },
    }
    (results_root / "legacy-provider-2026-07-26.json").write_text(
        json.dumps(report, sort_keys=True, indent=2), encoding="utf-8"
    )
    outcome = check_provider_gate(
        "legacy-provider",
        results_root=results_root,
        config=GateConfig(anti_lazy_conformance=DEFAULT_ANTI_LAZY_CONFORMANCE_THRESHOLD),
    )
    assert outcome.admitted is True


# ---------------------------------------------------------------------------
# Trivial-rate ceiling — closes module_01 flagged gap
# ---------------------------------------------------------------------------


def test_trivial_rate_ceiling_refuses_composer_when_exceeded():
    """Above-ceiling composer trivial rate refuses to compile a new suite."""
    history = tuple(
        HoldoutCompilationRecord(
            composer_name="cheap_composer",
            holdout_kind="trivial" if i < 15 else "real",
        )
        for i in range(20)
    )
    # 15/20 = 0.75, well above 0.3.
    with pytest.raises(TrivialRateCeilingExceededError):
        enforce_trivial_rate_ceiling(history, ceiling=0.3)


def test_trivial_rate_ceiling_admits_composer_within_bound():
    """Below-ceiling trivial rate lets the compile proceed."""
    history = tuple(
        HoldoutCompilationRecord(
            composer_name="reasonable_composer",
            holdout_kind="trivial" if i < 4 else "real",
        )
        for i in range(20)
    )
    # 4/20 = 0.20, below 0.3.
    enforce_trivial_rate_ceiling(history, ceiling=DEFAULT_TRIVIAL_RATE_CEILING)


# ---------------------------------------------------------------------------
# Second Pass Q2 — small-fix intent must NOT cry wolf
# ---------------------------------------------------------------------------


def test_small_fix_intent_does_not_over_estimate():
    """A one-line fix should produce a low expected number, not cry wolf."""
    ws = WorkspaceSnapshot(
        files={f"src/file{i}.py": f"def f{i}(): pass" for i in range(30)}
    )
    # Very targeted intent — one specific symbol.
    estimate = estimate_effort("fix off-by-one in file7 line 42", ws)
    # The estimator should NOT expect a wide surface.
    assert estimate.files_touched_expected <= 15


# ---------------------------------------------------------------------------
# Second Pass Q3 — intent-manipulation via keyword packing
# ---------------------------------------------------------------------------


def test_intent_manipulation_via_keyword_packing_filtered():
    """Common-in-workspace keywords are dropped as low-signal."""
    ws = WorkspaceSnapshot(
        files={f"src/test_module_{i}.py": "x" for i in range(20)}
    )
    # "test" and "module" appear in every filename — they must be
    # filtered so a model that packs them cannot amplify the estimate.
    kws = _extract_keywords(
        "test test test module module module refactor sparse_symbol",
        ws,
        max_filename_fraction=0.5,
    )
    assert "test" not in kws
    assert "module" not in kws
    # A rare-in-workspace keyword survives.
    assert "sparse_symbol" in kws or "refactor" in kws


# ---------------------------------------------------------------------------
# Depth-4 leaf checks
# ---------------------------------------------------------------------------


def test_antilazy_fixtures_dir_has_ten_intents():
    """DoD leaf (b): 10 fixtures with intent.txt / workspace/ / expected.json."""
    root = Path(__file__).resolve().parent.parent / "evals" / "conformance" / "anti_lazy"
    fixtures = [p for p in sorted(root.iterdir()) if p.is_dir()]
    assert len(fixtures) == 10
    for fx in fixtures:
        assert (fx / "intent.txt").is_file()
        assert (fx / "expected.json").is_file()
        assert (fx / "workspace").is_dir()


# ---------------------------------------------------------------------------
# Second Pass fixes — regression tests for the three concrete defects the
# reviewer named. Each test names the finding it locks in.
# ---------------------------------------------------------------------------


def test_extract_keywords_returns_empty_on_empty_workspace():
    """Second Pass reviewer Additional Defect #1 — empty workspace bypass.

    An empty workspace made the hit-fraction filter compute 0.0 for
    every token so every token passed as high-signal. The fix returns
    an empty tuple immediately so the caller enters its fallback path
    with no amplification opportunity.
    """
    ws = WorkspaceSnapshot(files={})
    assert _extract_keywords("pack pack pack tokens", ws) == ()


def test_short_code_token_bypass_filtered():
    """Second Pass reviewer Q3 — 4-char code tokens no longer pass.

    Tokens like ``handler``, ``service``, ``runner`` sat above
    ``min_length=4`` and were not in the previous stop-word set. The
    fix adds them to ``_STOP_WORDS`` and tightens the filename-hit
    filter to 0.15 so mid-frequency code tokens are dropped.
    """
    # A workspace with 20 files; ``rare_symbol`` names exactly one so
    # its filename-hit-fraction (0.05) sits under the tightened 0.15
    # cap, while the code-token attackers all fail the stop-word set.
    files = {f"src/mod{i}.py": "x" for i in range(19)}
    files["src/rare_symbol.py"] = "x"
    ws = WorkspaceSnapshot(files=files)
    kws = _extract_keywords(
        "handler service runner utils helper config rare_symbol", ws
    )
    for banned in ("handler", "service", "runner", "utils", "helper", "config"):
        assert banned not in kws, f"{banned} should have been filtered"
    assert "rare_symbol" in kws


def test_run_companion_report_time_matches_budget_flag():
    """Second Pass reviewer Additional Defect #3 — no elapsed-time disagreement.

    Previously ``time_spent_seconds`` was computed off a second
    monotonic read after the runner loop and ``time_exceeded`` off an
    adapter-only read; a report could show
    ``time_spent_seconds > budget`` while ``time_exceeded`` was set
    against a smaller number. The fix derives both from one
    measurement.
    """
    primary = _StubProvider(name="prov_primary")
    companion = _StubProvider(name="prov_companion")
    adapter = _SpyAdapter(provider_name=companion.name)
    # Fast-completing adapter with a generous budget: report must
    # record time_exceeded=False AND time_spent_seconds <= budget.
    config = CompanionConfig(provider=companion, time_budget_seconds=60)
    report = run_companion(
        intent="ok",
        diff=_make_patch(),
        visible_suite=_make_visible_suite(),
        config=config,
        adapter=adapter,
        primary=primary,
    )
    assert report.time_exceeded is False
    assert report.time_spent_seconds <= config.time_budget_seconds


def test_measure_actual_effort_from_patch():
    """measure_actual_effort reads a Patch and returns integer scalars."""
    patch = Patch(
        hunks=(
            Hunk(
                path="src/mod.py",
                added_lines=("def foo():", "    return 1"),
                removed_lines=(),
                start_line=1,
            ),
            Hunk(
                path="tests/test_mod.py",
                added_lines=("def test_foo():", "    assert foo() == 1"),
                removed_lines=(),
                start_line=1,
            ),
        )
    )
    actual = measure_actual_effort(patch)
    assert actual.files_touched_realized == 2
    assert actual.tests_added_or_updated_realized == 1
    assert actual.lines_changed_realized == 4


# RACT 0.4.0
