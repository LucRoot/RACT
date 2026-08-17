"""Tests for RelatedFileCoverageInvocation and compiler default coupling."""

from __future__ import annotations

from ract.core.compile import (
    CouplingMap,
    CompilerInputs,
    IntentCompiler,
    _DEFAULT_COUPLING_MAPS,
)
from ract.core.gates import evaluate_related_file_coverage
from ract.core.loop import WorkspaceSnapshot
from ract.core.predicate import RelatedFileCoverageInvocation


def _ws(changed: list[str] | None) -> WorkspaceSnapshot:
    metadata: dict[str, object] = {}
    if changed is not None:
        metadata["changed_files"] = list(changed)
    return WorkspaceSnapshot(files={}, timestamp=0.0, metadata=metadata)


def test_related_file_coverage_ok_when_both_touched() -> None:
    inv = RelatedFileCoverageInvocation(
        source_glob="src/ract/core/*.py",
        must_also_touch_glob="docs/ARCHITECTURE.md",
        rationale="arch changes require ARCHITECTURE.md update",
    )
    ws = _ws(["src/ract/core/loop.py", "docs/ARCHITECTURE.md"])
    result = evaluate_related_file_coverage(inv, ws)
    assert result.ok is True
    assert "src/ract/core/loop.py" in result.evidence["source_hits"]
    assert "docs/ARCHITECTURE.md" in result.evidence["target_hits"]


def test_related_file_coverage_fails_when_source_touched_but_not_target() -> None:
    inv = RelatedFileCoverageInvocation(
        source_glob="src/ract/core/*.py",
        must_also_touch_glob="docs/ARCHITECTURE.md",
        rationale="arch changes require ARCHITECTURE.md update",
    )
    ws = _ws(["src/ract/core/loop.py"])
    result = evaluate_related_file_coverage(inv, ws)
    assert result.ok is False
    assert "modified" in result.reason
    assert "docs/ARCHITECTURE.md" in result.reason
    assert result.evidence["target_hits"] == []


def test_related_file_coverage_ok_when_neither_touched() -> None:
    inv = RelatedFileCoverageInvocation(
        source_glob="src/ract/core/*.py",
        must_also_touch_glob="docs/ARCHITECTURE.md",
        rationale="arch changes require ARCHITECTURE.md update",
    )
    ws = _ws(["src/ract/cli.py", "README.md"])
    result = evaluate_related_file_coverage(inv, ws)
    assert result.ok is True
    assert "vacuously" in result.reason
    assert result.evidence["source_hits"] == []


def test_related_file_coverage_missing_diff_channel_is_unresolved() -> None:
    inv = RelatedFileCoverageInvocation(
        source_glob="src/ract/core/*.py",
        must_also_touch_glob="docs/ARCHITECTURE.md",
    )
    ws = _ws(None)
    result = evaluate_related_file_coverage(inv, ws)
    assert result.ok is False
    assert "no ws.metadata['changed_files']" in result.reason


def test_related_file_coverage_brace_expansion() -> None:
    """`{core,executor}` in the glob expands to both branches."""
    inv = RelatedFileCoverageInvocation(
        source_glob="src/ract/{core,executor}/*.py",
        must_also_touch_glob="docs/ARCHITECTURE.md",
    )
    ws = _ws(["src/ract/executor/loop.py", "docs/ARCHITECTURE.md"])
    result = evaluate_related_file_coverage(inv, ws)
    assert result.ok is True
    assert "src/ract/executor/loop.py" in result.evidence["source_hits"]


def test_compiler_adds_arch_coupling_for_core_changes() -> None:
    """Default coupling attaches when touched_surface hits core/executor."""
    compiler = IntentCompiler()
    ws = WorkspaceSnapshot(files={}, timestamp=0.0)
    inputs = CompilerInputs(
        touched_surface=("src/ract/core/loop.py",),
    )
    suite = compiler.compile("update core loop", ws, inputs=inputs)

    coupling_predicates = [
        p for p in suite.predicates if p.kind == "related_file_coverage"
    ]
    assert coupling_predicates, "expected at least one related_file_coverage predicate"

    default = _DEFAULT_COUPLING_MAPS[0]
    matched = [
        p
        for p in coupling_predicates
        if isinstance(p.invocation, RelatedFileCoverageInvocation)
        and p.invocation.source_glob == default.source_glob
        and p.invocation.must_also_touch_glob == default.must_also_touch_glob
    ]
    assert matched, "default arch coupling missing"


def test_compiler_skips_default_coupling_for_unrelated_intent() -> None:
    """Intents that don't touch core/executor don't get the default gate."""
    compiler = IntentCompiler()
    ws = WorkspaceSnapshot(files={}, timestamp=0.0)
    inputs = CompilerInputs(touched_surface=("README.md",))
    suite = compiler.compile("edit readme", ws, inputs=inputs)

    coupling = [p for p in suite.predicates if p.kind == "related_file_coverage"]
    assert coupling == []


def test_compiler_accepts_custom_coupling_maps() -> None:
    compiler = IntentCompiler()
    ws = WorkspaceSnapshot(files={}, timestamp=0.0)
    inputs = CompilerInputs(
        coupling_maps=(
            CouplingMap(
                source_glob="src/lib/*.py",
                must_also_touch_glob="CHANGELOG.md",
                rationale="lib changes must be logged",
            ),
        ),
        include_default_coupling_maps=False,
    )
    suite = compiler.compile("any", ws, inputs=inputs)

    coupling = [p for p in suite.predicates if p.kind == "related_file_coverage"]
    assert len(coupling) == 1
    inv = coupling[0].invocation
    assert isinstance(inv, RelatedFileCoverageInvocation)
    assert inv.source_glob == "src/lib/*.py"
    assert inv.must_also_touch_glob == "CHANGELOG.md"


# RACT 0.4.1
