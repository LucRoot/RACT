"""Tests for ALM module_06 — isomorphic perturbation gate.

Seven tests, one per Definition-of-Done leaf plus lateral-chain branches:

- ``test_detector_fires_on_universal_quantifier`` — intent "every user
  has exactly one primary email" returns ``rule_like=True``.
- ``test_detector_does_not_fire_on_open_ended`` — intent "refactor
  for readability" returns ``rule_like=False``.
- ``test_transformations_produce_three_variants`` — ``transform_intent``
  returns three variants with distinct kinds.
- ``test_ast_normalized_comparison_ignores_renaming`` — a solution and
  its renamed twin compare equal after applying the renaming map.
- ``test_divergence_emits_violation_and_resumes_loop`` — a synthetic run
  where the transformed solution diverges from the original; the gate
  blocks COMPLETE and emits ``laziness.violated``.
- ``test_gate_does_not_fire_on_non_rule_like`` — an open-ended intent
  runs to completion without invoking ``run_iso_perturbation``.
- ``test_report_written_to_run_directory`` — ``iso_perturb.json`` is
  written under the report directory after every rule-like completion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ract.antilazy.iso_perturb import (
    IsoPerturbBundle,
    IsoPerturbConfig,
    IsomorphicTransformation,
    compare_solutions,
    detect_rule_like_intent,
    run_iso_perturb_gate,
    transform_intent,
)
from ract.core.loop import WorkspaceSnapshot
from ract.trace.sink import clear_writer, set_writer
from ract.trace.writer import JsonlEventWriter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StaticProducer:
    """SolutionProducer that returns a fixed string, ignoring the intent."""

    def __init__(self, solution: str) -> None:
        self._solution = solution

    def produce(self, intent: str, workspace: WorkspaceSnapshot) -> str:  # noqa: ARG002
        return self._solution


class _RenameSensitiveProducer:
    """Returns different solutions depending on whether the intent was renamed.

    The audit-logger fixture: the original intent mentions
    ``audit_logger``; the renamed variant mentions ``ledger_recorder``.
    A pattern-matching primary echoes the exact vocabulary and so
    diverges under AST normalization.
    """

    def produce(self, intent: str, workspace: WorkspaceSnapshot) -> str:  # noqa: ARG002
        text = intent.lower()
        if "recorder" in text or "ledger" in text and "logger" not in text:
            return "def wrap():\n    return ledger_recorder(fn)\n"
        return "def wrap():\n    return audit_logger(fn)\n"


def _blank_workspace() -> WorkspaceSnapshot:
    return WorkspaceSnapshot(files={})


# ---------------------------------------------------------------------------
# Test 1 — detector fires on universal quantifier
# ---------------------------------------------------------------------------


def test_detector_fires_on_universal_quantifier() -> None:
    detection = detect_rule_like_intent("every user has exactly one primary email")
    assert detection.is_rule_like is True
    assert detection.confidence >= 0.7
    # At least one of the universal keywords must appear in the
    # matched set.
    matched = set(detection.matched_keywords)
    assert matched & {"every", "all", "exactly one", "no", "must", "has"}


# ---------------------------------------------------------------------------
# Test 2 — detector does not fire on open-ended intents
# ---------------------------------------------------------------------------


def test_detector_does_not_fire_on_open_ended() -> None:
    detection = detect_rule_like_intent(
        "refactor the report renderer for readability. Split long "
        "helpers into smaller ones."
    )
    assert detection.is_rule_like is False
    assert detection.confidence < 0.7
    assert detection.matched_keywords == ()


# ---------------------------------------------------------------------------
# Test 3 — transformations produce three distinct variants
# ---------------------------------------------------------------------------


def test_transformations_produce_three_variants() -> None:
    intent = (
        "Every user must have exactly one primary email. "
        "The examples are:\n- alice@example.com\n- bob@example.com"
    )
    variants = transform_intent(intent)
    assert len(variants) == 3
    kinds = tuple(v.kind for v in variants)
    assert kinds == (
        "rename_entities",
        "swap_syntax",
        "permute_examples",
    )
    # The three transformed intents differ from each other AND at
    # least the rename-entities variant differs from the original.
    transformed_texts = {v.transformed_intent for v in variants}
    assert len(transformed_texts) >= 2
    rename = variants[0]
    assert rename.renaming_map, (
        "rename_entities transformation should have produced a "
        "non-empty renaming map on an intent containing "
        "renameable entities (user, email, primary)."
    )
    # Workspace symbols are preserved.
    variants_preserved = transform_intent(intent, workspace_symbols=frozenset({"user"}))
    rename_preserved = variants_preserved[0]
    assert "user" not in rename_preserved.renaming_map, (
        "workspace-symbol 'user' should have been preserved on rename"
    )


# ---------------------------------------------------------------------------
# Test 4 — AST-normalized comparison ignores renaming
# ---------------------------------------------------------------------------


def test_ast_normalized_comparison_ignores_renaming() -> None:
    original = "def send(user, email):\n    return log(user, email)\n"
    renamed = "def send(member, address):\n    return log(member, address)\n"
    transformation = IsomorphicTransformation(
        kind="rename_entities",
        transformed_intent="(unused)",
        renaming_map={"user": "member", "email": "address"},
    )
    similarity, reason = compare_solutions(
        original, renamed, transformation=transformation
    )
    assert reason is None
    assert similarity == 1.0
    # Sanity: without applying the renaming map, the two solutions
    # would NOT compare equal.
    similarity_raw, reason_raw = compare_solutions(
        original,
        renamed,
        transformation=IsomorphicTransformation(
            kind="swap_syntax",
            transformed_intent="(unused)",
            renaming_map={},
        ),
    )
    assert reason_raw == "ast_dump_mismatch"
    assert similarity_raw < 1.0


# ---------------------------------------------------------------------------
# Test 5 — divergence emits violation and blocks COMPLETE
# ---------------------------------------------------------------------------


def test_divergence_emits_violation_and_resumes_loop(tmp_path: Path) -> None:
    log_file = tmp_path / "trace.jsonl"
    writer = JsonlEventWriter(log_file, run_id=b"\x00" * 16)
    set_writer(writer)
    try:
        producer = _RenameSensitiveProducer()
        bundle = IsoPerturbBundle(
            primary=producer,
            report_dir=tmp_path / "runs",
            config=IsoPerturbConfig(similarity_threshold=0.95),
        )
        outcome = run_iso_perturb_gate(
            intent=(
                "Every function that mutates the ledger must route "
                "through the audit logger; no function may bypass "
                "the audit logger."
            ),
            workspace=_blank_workspace(),
            original_solution="def wrap():\n    return audit_logger(fn)\n",
            bundle=bundle,
            run_id="run-000",
        )
    finally:
        clear_writer()

    assert outcome.blocks_complete is True
    assert outcome.report is not None
    assert outcome.report.is_pattern_matching is True
    assert outcome.resume_prompt.startswith("[ISOMORPHIC DIVERGENCE]")
    # At least one divergence is on the rename transformation.
    rename_divergences = [
        d
        for d in outcome.report.divergences
        if d.transformation_kind == "rename_entities"
    ]
    assert rename_divergences, (
        "expected the rename transformation to diverge for the pattern-matching primary"
    )
    # The trace file has a laziness.violated event with the
    # isomorphic_divergence kind.
    events = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    violated = [
        e
        for e in events
        if e.get("kind") == "laziness.violated"
        and e.get("payload", {}).get("kind") == "isomorphic_divergence"
    ]
    assert len(violated) == 1, f"expected one violation, got {violated}"


# ---------------------------------------------------------------------------
# Test 6 — gate does not fire on non-rule-like intents
# ---------------------------------------------------------------------------


def test_gate_does_not_fire_on_non_rule_like(tmp_path: Path) -> None:
    calls: list[str] = []

    class _RecordingProducer:
        def produce(self, intent: str, workspace: WorkspaceSnapshot) -> str:  # noqa: ARG002
            calls.append(intent)
            return "def f(): pass\n"

    bundle = IsoPerturbBundle(
        primary=_RecordingProducer(),
        report_dir=tmp_path / "runs",
    )
    outcome = run_iso_perturb_gate(
        intent=(
            "Refactor the report renderer for readability. Split "
            "long helpers into smaller ones."
        ),
        workspace=_blank_workspace(),
        original_solution="def f(): pass\n",
        bundle=bundle,
        run_id="run-001",
    )
    assert outcome.blocks_complete is False
    assert outcome.report is None
    assert outcome.skipped_reason == "non_rule_like"
    # The producer was never called — the detector short-circuited
    # before any transformation dispatch.
    assert calls == []
    # No report file was written either.
    assert not (tmp_path / "runs" / "run-001" / "iso_perturb.json").exists()


# ---------------------------------------------------------------------------
# Test 7 — report written to run directory
# ---------------------------------------------------------------------------


def test_report_written_to_run_directory(tmp_path: Path) -> None:
    producer = _StaticProducer("def cents(x: int) -> int:\n    return int(x)\n")
    bundle = IsoPerturbBundle(
        primary=producer,
        report_dir=tmp_path / "runs",
        # Static producer returns the identical string for every
        # transformed intent, so the gate finds no divergence.
        config=IsoPerturbConfig(similarity_threshold=0.9),
    )
    outcome = run_iso_perturb_gate(
        intent=(
            "All monetary values must be stored as integer cents; "
            "no floating-point representation may enter the money "
            "module."
        ),
        workspace=_blank_workspace(),
        original_solution="def cents(x: int) -> int:\n    return int(x)\n",
        bundle=bundle,
        run_id="run-002",
    )
    assert outcome.blocks_complete is False
    assert outcome.report is not None
    assert outcome.report.is_pattern_matching is False
    # DoD depth-4 leaf (b) — the file must exist on every rule-like
    # completion.
    report_path = tmp_path / "runs" / "run-002" / "iso_perturb.json"
    assert report_path.exists()
    payload: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["is_pattern_matching"] is False
    assert len(payload["transformations"]) == 3
    assert len(payload["transformed_solution_digests"]) == 3
    assert payload["original_solution_digest"], "digest hex should be non-empty"
    # Schema keys per module_06.md step 4 leaf (b).
    assert set(payload.keys()) == {
        "original_intent",
        "transformations",
        "original_solution_digest",
        "transformed_solution_digests",
        "divergences",
        "is_pattern_matching",
    }


# ---------------------------------------------------------------------------
# Additional guard: compile pass tags rule_like on the intent
# ---------------------------------------------------------------------------


def test_compile_pass_tags_rule_like() -> None:
    """The IntentCompiler surfaces the rule-like flag alongside the suite.

    DoD bullet: "the compile pass tags the intent rule_like=True."
    """
    from ract.core.compile import CompilerInputs, IntentCompiler
    from ract.core.loop import WorkspaceSnapshot

    compiler = IntentCompiler()
    ws = WorkspaceSnapshot(files={})
    inputs = CompilerInputs()
    _suite_rule, is_rule_like = compiler.compile_and_detect_rule_like(
        "Every user must have exactly one primary email", ws, inputs=inputs
    )
    assert is_rule_like is True

    _suite_open, is_rule_like_open = compiler.compile_and_detect_rule_like(
        "refactor the renderer for readability", ws, inputs=inputs
    )
    assert is_rule_like_open is False


# ---------------------------------------------------------------------------
# Regression tests for Second Pass external-reviewer findings
# ---------------------------------------------------------------------------


def test_rename_degeneracy_advisory_fires_when_workspace_symbols_flood(
    tmp_path: Path,
) -> None:
    """Second Pass Q1: rename degeneracy advisory catches the flood attack.

    A caller that dumps every ordinary noun into ``workspace_symbols``
    turns the rename into a no-op. The advisory event surfaces the
    degeneracy so operators can compensate.
    """
    from ract.antilazy.iso_perturb import (
        rename_map_degeneracy_ratio,
        transform_intent,
    )

    intent = (
        "All monetary values must be stored as integer cents; no "
        "floating-point representation may enter the money module."
    )
    # Flood workspace_symbols with the intent's own vocabulary.
    flood = frozenset(
        {
            "monetary",
            "values",
            "integer",
            "cents",
            "floating",
            "point",
            "representation",
            "money",
            "module",
        }
    )
    variants = transform_intent(intent, workspace_symbols=flood)
    rename = variants[0]
    ratio = rename_map_degeneracy_ratio(intent, rename.renaming_map)
    # With the flood the map is empty (or nearly so).
    assert ratio < 0.10, f"expected degenerate ratio, got {ratio}"

    # And the advisory event fires when run_iso_perturbation sees
    # the degeneracy.
    log_file = tmp_path / "trace.jsonl"
    writer = JsonlEventWriter(log_file, run_id=b"\x00" * 16)
    set_writer(writer)
    try:
        from ract.antilazy.iso_perturb import run_iso_perturbation

        run_iso_perturbation(
            intent=intent,
            workspace=_blank_workspace(),
            original_solution="def cents(x: int) -> int:\n    return int(x)\n",
            primary=_StaticProducer("def cents(x: int) -> int:\n    return int(x)\n"),
            workspace_symbols=flood,
        )
    finally:
        clear_writer()
    events = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    degenerates = [
        e
        for e in events
        if e.get("kind") == "laziness.violated"
        and e.get("payload", {}).get("kind") == "iso_perturb_rename_degenerate"
    ]
    assert degenerates, "expected the rename-degeneracy advisory to fire"
    assert degenerates[0]["payload"]["advisory"] is True


def test_camelcase_and_underscore_identifiers_are_renamed() -> None:
    """Second Pass Additional #2: multi-part identifiers get renamed.

    ``primaryEmail`` and ``audit_logger`` are single tokens under
    naive isalpha() but should split into renameable parts.
    """
    from ract.antilazy.iso_perturb import _split_intent_tokens, transform_intent

    tokens = _split_intent_tokens("primaryEmail audit_logger")
    alpha = [t for t in tokens if t.isalpha()]
    assert "primary" in alpha
    assert "Email" in alpha
    assert "audit" in alpha
    assert "logger" in alpha

    intent = "Every function must route through the audit_logger and primaryEmail must be unique."
    variants = transform_intent(intent)
    rename = variants[0]
    # audit and logger both renamed from the synonym table.
    assert rename.renaming_map.get("audit") == "ledger"
    assert rename.renaming_map.get("logger") == "recorder"
    # primary renamed too (present in synonym table).
    assert rename.renaming_map.get("primary") == "default"
    # Email (title-case) renames to Address via the case-preserving
    # branch — the tokenizer surfaced Email as a candidate token and
    # the synonym table (email -> address) fired with title-case
    # preservation.
    assert rename.renaming_map.get("Email") == "Address"


def test_producer_error_emits_distinct_advisory(tmp_path: Path) -> None:
    """Second Pass Additional #4: producer errors are distinguishable."""
    from ract.antilazy.iso_perturb import run_iso_perturbation

    class _RaisingProducer:
        def produce(self, intent: str, workspace: WorkspaceSnapshot) -> str:  # noqa: ARG002
            raise ConnectionError("simulated outage")

    log_file = tmp_path / "trace.jsonl"
    writer = JsonlEventWriter(log_file, run_id=b"\x00" * 16)
    set_writer(writer)
    try:
        report = run_iso_perturbation(
            intent=(
                "Every function must route through the audit logger; "
                "no function may bypass the audit logger."
            ),
            workspace=_blank_workspace(),
            original_solution="def wrap():\n    return audit_logger(fn)\n",
            primary=_RaisingProducer(),
        )
    finally:
        clear_writer()
    # Divergences reflect the missing solutions (loop still blocks).
    assert report.is_pattern_matching is True
    assert all(d.reason == "solution_missing" for d in report.divergences)
    # A dedicated advisory landed per errored producer call so
    # operators can distinguish outage from pattern-match.
    events = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    producer_errs = [
        e
        for e in events
        if e.get("kind") == "laziness.violated"
        and e.get("payload", {}).get("kind") == "iso_perturb_producer_error"
    ]
    assert producer_errs, "expected iso_perturb_producer_error advisories"
    assert producer_errs[0]["payload"]["exception_class"] == "ConnectionError"
    assert producer_errs[0]["payload"]["advisory"] is True


def test_permute_examples_handles_duplicate_quoted_items() -> None:
    """Second Pass Additional #6: duplicate quoted items do not cross-contaminate."""
    from ract.antilazy.iso_perturb import _apply_permute_examples

    intent = 'Options are "alice", "bob", "alice" for the fixture.'
    permuted = _apply_permute_examples(intent)
    # Reversing ["alice", "bob", "alice"] yields ["alice", "bob", "alice"]
    # — palindrome — so the permutation is a no-op AND no sentinel
    # bleed appears in the output.
    assert "\x00" not in permuted
    assert "ISO_PERM" not in permuted
    # Sanity: a non-palindrome permutes correctly.
    intent_np = 'Options are "alice", "bob", "carol" for the fixture.'
    permuted_np = _apply_permute_examples(intent_np)
    assert "\x00" not in permuted_np
    assert "ISO_PERM" not in permuted_np
    # The original order was alice, bob, carol; the reversed shows
    # carol first.
    assert permuted_np.index('"carol"') < permuted_np.index('"alice"')


def test_low_confidence_intent_runs_one_transformation(tmp_path: Path) -> None:
    """Second Pass Additional #7: low-confidence branch runs exactly one variant."""
    from ract.antilazy.iso_perturb import (
        detect_rule_like_intent,
        run_iso_perturbation,
    )

    # A modal-only intent with no verb hint in the 60-char window.
    intent = "Callers must remember the guidance."
    detection = detect_rule_like_intent(intent)
    assert detection.is_rule_like is True
    assert 0.7 <= detection.confidence < 0.8, (
        f"expected modal-only confidence in [0.7, 0.8), got {detection.confidence}"
    )
    producer = _StaticProducer("def f():\n    pass\n")
    report = run_iso_perturbation(
        intent=intent,
        workspace=_blank_workspace(),
        original_solution="def f():\n    pass\n",
        primary=producer,
    )
    # Below the 0.7 threshold-for-full-gate, only one variant runs.
    # (The default threshold is 0.7 and confidence is 0.7; equal
    # means at-or-above so full gate runs. Force low with a config.)
    from ract.antilazy.iso_perturb import IsoPerturbConfig

    report_low = run_iso_perturbation(
        intent=intent,
        workspace=_blank_workspace(),
        original_solution="def f():\n    pass\n",
        primary=producer,
        config=IsoPerturbConfig(confidence_threshold_for_full_gate=0.9),
    )
    assert len(report_low.transformations) == 1
    assert report_low.transformations[0].kind == "rename_entities"
    # And at-or-above threshold: all three variants.
    assert len(report.transformations) == 3


# RACT 0.4.0
