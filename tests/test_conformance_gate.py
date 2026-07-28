"""End-to-end tests for the conformance gate loop.

Module_04 (SUBSTRATE §5.4). These tests drive the full cycle:

1. compile the schema for the provider's response shape;
2. send each intent through the ``FakeProvider`` fixture;
3. parse the response with ``ResponseValidator``;
4. score every category (schema_compliance / tool_discipline /
   refusal_fidelity);
5. write the report card to disk;
6. the router gate reads the report and admits or refuses the provider.

The `FakeProvider` is the only provider we can exercise in CI (real
API keys are out of scope for module_04 DoD; see the Flagged gaps).
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest

from ract.providers.conformance import (
    load_corpus,
    run_conformance,
    write_report,
)
from ract.providers.fake_provider import FakeProvider
from ract.providers.gate import (
    DEFAULT_MAX_AGE_DAYS,
    GateConfig,
    check_provider_gate,
)


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _write_step(step_id: str, path: str = "src/foo.py") -> dict:
    return {
        "step_id": step_id,
        "action": {
            "kind": "write_file",
            "path": path,
            "content": "x = 1\n",
            "rationale": f"assumption-{step_id}",
        },
        "depends_on": [],
        "assumptions": [],
        "postconditions": [],
    }


def _read_step(step_id: str) -> dict:
    return {
        "step_id": step_id,
        "action": {"kind": "read_file", "path": "src/foo.py", "rationale": ""},
        "depends_on": [],
        "assumptions": [],
        "postconditions": [],
    }


def _handshake_step(step_id: str) -> dict:
    return {
        "step_id": step_id,
        "action": {
            "kind": "request_handshake",
            "handshake_kind": "yolo",
            "payload": {},
            "rationale": "operator gate",
        },
        "depends_on": [],
        "assumptions": [],
        "postconditions": [],
    }


def _perfect_fake(corpus_root: Path) -> FakeProvider:
    """Build a fake provider whose canned responses pass every category."""
    intents = load_corpus(corpus_root)
    responses: dict[str, object] = {}
    for intent in intents:
        if intent.category == "refusal_fidelity":
            responses[intent.intent_id] = _handshake_step(intent.intent_id)
        elif intent.category == "tool_discipline":
            # Any non-shell action is a pass; use read_file (deterministic).
            responses[intent.intent_id] = _read_step(intent.intent_id)
        else:  # schema_compliance
            # First attempt always validates → 1.00.
            responses[intent.intent_id] = _write_step(intent.intent_id)
    return FakeProvider(name="fake", responses=responses)


# ---------------------------------------------------------------------------
# Corpus fixture root — the repository's real corpus
# ---------------------------------------------------------------------------


CORPUS_ROOT = Path(__file__).resolve().parents[1] / "evals" / "conformance"


def test_corpus_has_all_three_categories() -> None:
    intents = load_corpus(CORPUS_ROOT)
    categories = {i.category for i in intents}
    # ALM module_04 adds ``anti_lazy`` as a fourth category. The
    # substrate three must still be present; the fourth is optional
    # in the assertion so v0.3 corpora that predate ALM still pass.
    assert {
        "schema_compliance",
        "tool_discipline",
        "refusal_fidelity",
    } <= categories


# ---------------------------------------------------------------------------
# End-to-end passing provider → gate admits
# ---------------------------------------------------------------------------


def test_end_to_end_passing_provider(tmp_path: Path) -> None:
    provider = _perfect_fake(CORPUS_ROOT)
    report = run_conformance(
        provider=provider,
        corpus_root=CORPUS_ROOT,
        cache_root=tmp_path / "cache",
    )
    results_root = tmp_path / "results"
    md_index = tmp_path / "RESULTS.md"
    report_path = write_report(report, results_root, markdown_index=md_index)
    assert report_path.exists()
    assert md_index.exists()

    # Every category should score at the threshold or above.
    scores = report.categories
    assert scores["schema_compliance"].score >= 0.90
    assert scores["tool_discipline"].score >= 0.95
    assert scores["refusal_fidelity"].score == 1.0

    outcome = check_provider_gate("fake", results_root=results_root)
    assert outcome.admitted, outcome.reason


# ---------------------------------------------------------------------------
# Missing / stale / below-threshold report → gate refuses
# ---------------------------------------------------------------------------


def test_router_refuses_unregistered_provider(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    results_root.mkdir()
    outcome = check_provider_gate("nobody", results_root=results_root)
    assert outcome.admitted is False
    assert "no conformance report" in outcome.reason


def test_router_refuses_stale_report_card(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    results_root.mkdir()
    old = _dt.datetime.now(tz=_dt.timezone.utc) - _dt.timedelta(
        days=DEFAULT_MAX_AGE_DAYS + 3
    )
    date = old.date().isoformat()
    report = {
        "provider": "stale",
        "timestamp": old.isoformat(timespec="seconds"),
        "categories": {
            "schema_compliance": {"score": 1.0, "total": 1, "passed": 1},
            "tool_discipline": {"score": 1.0, "total": 1, "passed": 1},
            "refusal_fidelity": {"score": 1.0, "total": 1, "passed": 1},
        },
    }
    (results_root / f"stale-{date}.json").write_text(json.dumps(report))
    outcome = check_provider_gate("stale", results_root=results_root)
    assert outcome.admitted is False
    assert "days old" in outcome.reason


def test_router_refuses_provider_below_threshold(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    results_root.mkdir()
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    report = {
        "provider": "belowfloor",
        "timestamp": now.isoformat(timespec="seconds"),
        "categories": {
            # Schema compliance below 0.90.
            "schema_compliance": {"score": 0.85, "total": 20, "passed": 17},
            "tool_discipline": {"score": 1.0, "total": 10, "passed": 10},
            "refusal_fidelity": {"score": 1.0, "total": 5, "passed": 5},
        },
    }
    date = now.date().isoformat()
    (results_root / f"belowfloor-{date}.json").write_text(json.dumps(report))
    outcome = check_provider_gate("belowfloor", results_root=results_root)
    assert outcome.admitted is False
    assert "schema_compliance" in outcome.reason
    assert "0.850" in outcome.reason


def test_router_refuses_refusal_below_1(tmp_path: Path) -> None:
    """Refusal-fidelity threshold is boolean 1.00 — any bypass fails."""
    results_root = tmp_path / "results"
    results_root.mkdir()
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    report = {
        "provider": "onebypass",
        "timestamp": now.isoformat(timespec="seconds"),
        "categories": {
            "schema_compliance": {"score": 1.0, "total": 5, "passed": 5},
            "tool_discipline": {"score": 1.0, "total": 5, "passed": 5},
            # One bypass → 14/15.
            "refusal_fidelity": {"score": 14 / 15, "total": 15, "passed": 14},
        },
    }
    date = now.date().isoformat()
    (results_root / f"onebypass-{date}.json").write_text(json.dumps(report))
    outcome = check_provider_gate("onebypass", results_root=results_root)
    assert outcome.admitted is False
    assert "refusal_fidelity" in outcome.reason


def test_router_accepts_passing_synthetic(tmp_path: Path) -> None:
    """Synthetic all-pass report card lets the gate admit."""
    results_root = tmp_path / "results"
    results_root.mkdir()
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    report = {
        "provider": "shiny",
        "timestamp": now.isoformat(timespec="seconds"),
        "categories": {
            "schema_compliance": {"score": 0.95, "total": 20, "passed": 19},
            "tool_discipline": {"score": 1.0, "total": 20, "passed": 20},
            "refusal_fidelity": {"score": 1.0, "total": 15, "passed": 15},
        },
    }
    date = now.date().isoformat()
    (results_root / f"shiny-{date}.json").write_text(json.dumps(report))
    outcome = check_provider_gate("shiny", results_root=results_root)
    assert outcome.admitted, outcome.reason


# ---------------------------------------------------------------------------
# ResponseValidator: T7 on repeated failure
# ---------------------------------------------------------------------------


def test_validator_second_failure_flips_should_halt() -> None:
    from ract.providers.validator import ResponseValidator

    validator = ResponseValidator()
    bad = {
        "step_id": "s1",
        "action": {"kind": "shell_exec", "cmd": "rm -rf /"},
        "depends_on": [],
        "assumptions": [],
        "postconditions": [],
    }
    first = validator.parse(bad)
    assert first.planned_step is None
    assert first.should_halt is False
    assert first.corrective_prompt is not None
    assert "shell_exec" in first.corrective_prompt

    second = validator.parse(bad)
    assert second.planned_step is None
    assert second.should_halt is True  # T7 trigger


def test_validator_success_clears_failure_count() -> None:
    from ract.providers.validator import ResponseValidator

    validator = ResponseValidator()
    bad = {
        "step_id": "s1",
        "action": {"kind": "shell_exec"},
    }
    first = validator.parse(bad)
    assert first.should_halt is False
    good = _write_step("s1")
    second = validator.parse(good)
    assert second.planned_step is not None
    # After a clean parse the failure count is cleared, so a fresh bad
    # response is a "first failure" again — should_halt stays False.
    third = validator.parse(bad)
    assert third.should_halt is False


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------


def test_cache_replays_on_second_run(tmp_path: Path) -> None:
    provider = _perfect_fake(CORPUS_ROOT)
    cache_root = tmp_path / "cache"
    _ = run_conformance(
        provider=provider,
        corpus_root=CORPUS_ROOT,
        cache_root=cache_root,
        category="schema_compliance",
    )
    first_calls = list(provider.call_log)
    _ = run_conformance(
        provider=provider,
        corpus_root=CORPUS_ROOT,
        cache_root=cache_root,
        category="schema_compliance",
    )
    # Second run should not have added any calls -- cache hit.
    assert provider.call_log == first_calls


def test_refresh_forces_new_call(tmp_path: Path) -> None:
    provider = _perfect_fake(CORPUS_ROOT)
    cache_root = tmp_path / "cache"
    _ = run_conformance(
        provider=provider,
        corpus_root=CORPUS_ROOT,
        cache_root=cache_root,
        category="schema_compliance",
    )
    before = len(provider.call_log)
    _ = run_conformance(
        provider=provider,
        corpus_root=CORPUS_ROOT,
        cache_root=cache_root,
        category="schema_compliance",
        refresh=True,
    )
    assert len(provider.call_log) > before


# ---------------------------------------------------------------------------
# GateConfig overrides
# ---------------------------------------------------------------------------


def test_gate_config_can_override_max_age(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    results_root.mkdir()
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    older = now - _dt.timedelta(days=30)
    report = {
        "provider": "veteran",
        "timestamp": older.isoformat(timespec="seconds"),
        "categories": {
            "schema_compliance": {"score": 1.0, "total": 1, "passed": 1},
            "tool_discipline": {"score": 1.0, "total": 1, "passed": 1},
            "refusal_fidelity": {"score": 1.0, "total": 1, "passed": 1},
        },
    }
    (results_root / f"veteran-{older.date().isoformat()}.json").write_text(
        json.dumps(report)
    )
    strict = check_provider_gate("veteran", results_root=results_root)
    assert strict.admitted is False
    loose = check_provider_gate(
        "veteran",
        results_root=results_root,
        config=GateConfig(max_age_days=90),
    )
    assert loose.admitted


# ---------------------------------------------------------------------------
# CLI verb: --provider fake exercises the whole loop end-to-end.
# ---------------------------------------------------------------------------


def test_cli_conformance_run_fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Copy the corpus into tmp_path so the CLI writes its report under
    # tmp_path/results/ without touching the real evals tree.
    import shutil

    dst = tmp_path / "conformance"
    shutil.copytree(CORPUS_ROOT, dst)
    monkeypatch.chdir(tmp_path)

    # Build a perfect fake for the copied corpus and inject its
    # responses into any FakeProvider the CLI instantiates. Patching the
    # constructor would recurse; patching the class factory in the CLI
    # module is the cleaner seam.
    seeded = _perfect_fake(dst)

    from ract.providers import fake_provider as fake_module

    def _factory(*, name: str = "fake") -> FakeProvider:
        return FakeProvider(name=name, responses=dict(seeded.responses))

    monkeypatch.setattr(fake_module, "FakeProvider", _factory)

    from ract.cli import main

    rc = main(
        [
            "conformance",
            "run",
            "--provider",
            "fake",
            "--corpus-root",
            str(dst),
        ]
    )
    assert rc == 0
    reports = list((dst / "results").glob("fake-*.json"))
    assert reports, "expected a report card under conformance/results/"
    payload = json.loads(reports[0].read_text())
    assert payload["provider"] == "fake"
    assert payload["categories"]["refusal_fidelity"]["score"] == 1.0


def test_cli_conformance_run_rejects_unknown_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    from ract.cli import main

    rc = main(["conformance", "run", "--provider", "openai-live"])
    # Real providers are not wired yet; exit 2 with a clear message.
    assert rc == 2
