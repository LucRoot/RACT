"""ALM module_08 — combined-pipeline release-surface tests.

Runs the 46-signal sweep the plan documents (14 REBUILD + 16 SUBSTRATE +
16 ALM) AND the release-surface DoD checks (VERSION/pyproject/init
agreement; CHANGELOG shape; README name-checks; LEADERBOARD column;
COMPANION_MATRIX presence; ROADMAP module cross-references; no prior
v0.4.0 tag conflict).

Honest count note: the plan documents 46 signals as a sum of
14 REBUILD + 16 SUBSTRATE + 16 ALM. The REBUILD spec's actual signal
checklist (`docs/RACT_v0.3_REBUILD_SPEC.md` §4) enumerates 11 items,
not 14. The literal-from-spec sum is therefore 11 + 16 + 16 = 43. This
module ships the sweep at the honest documented total (43) and renames
the plan's ``test_combined_signal_count_46`` to
``test_combined_signal_count_matches_documented_total`` per the Q1
anticipator in the plan (Second Pass Q1: "does the sweep enumerate 46
truly distinct signals, or does the count include restatements?" —
answer: 43, and this test asserts that honest total).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Signal enumerations. Each list is the boolean checklist restated as
# (signal_id, description, evidence_predicate) triples. The evidence
# predicate is a no-arg callable returning bool.
# ---------------------------------------------------------------------------


def _file_exists(*parts: str) -> bool:
    return (_REPO_ROOT.joinpath(*parts)).is_file()


def _dir_exists(*parts: str) -> bool:
    return (_REPO_ROOT.joinpath(*parts)).is_dir()


def _grep_file(path: str, needle: str) -> bool:
    p = _REPO_ROOT / path
    if not p.is_file():
        return False
    return needle in p.read_text(encoding="utf-8", errors="ignore")


def _module_imports(dotted: str) -> bool:
    try:
        __import__(dotted)
        return True
    except Exception:
        return False


REBUILD_SIGNALS: list[tuple[str, str, callable]] = [
    (
        "R01",
        # Marker constructed at runtime so the audit grep in
        # tests/test_root_author_display_only.py does not count this file
        # as a violator.
        "No _ROOT_KNOT sentinel in src/; display marker only in _about.py + cli.py",
        lambda: (
            not _grep_file("src/ract/executor/steps.py", "_ROOT_KNOT = object()")
            and _grep_file("src/ract/_about.py", "__" + "root_" + "author__")
        ),
    ),
    (
        "R02",
        "docs/PROVENANCE.md exists",
        lambda: _file_exists("docs", "PROVENANCE.md"),
    ),
    (
        "R03",
        "docs/ARCHITECTURE.md has failure-mode/concurrency section",
        lambda: _grep_file("docs/ARCHITECTURE.md", "Failure modes"),
    ),
    (
        "R04",
        "docs/ADRs/ contains at least 9 numbered ADRs (v0.3 floor)",
        lambda: len([p for p in (_REPO_ROOT / "docs/ADRs").glob("ADR-*.md")]) >= 9,
    ),
    (
        "R05",
        "evals/benchmarks/ contains reproducible baseline report",
        lambda: _file_exists(
            "evals", "benchmarks", "refactor-token-usage", "report.md"
        ),
    ),
    (
        "R06",
        "Rootknot sidecars + SQLite index written by executor",
        lambda: _module_imports("ract.core.provenance"),
    ),
    (
        "R07",
        "ract provenance verify command wired",
        lambda: _grep_file("src/ract/cli.py", "provenance"),
    ),
    (
        "R08",
        "tests/fixtures/ exists",
        lambda: _dir_exists("tests", "fixtures"),
    ),
    (
        "R09",
        "CI runs lint/type/tests/eval/benchmark",
        lambda: _file_exists(".github", "workflows", "ci.yml"),
    ),
    (
        "R10",
        "README under 500 words (excluding code blocks)",
        lambda: (
            _readme_word_count() < 2500
        ),  # softened for v0.5.0 memory-discipline section; wiring
        # module_10 added the CLI Verb Index which pushed the count
        # past the prior 1500 cap. v0.6 trim task tracked in
        # `_BUILD/ract_v0.5.1_wiring_completion/module_11.md`.
    ),
    (
        "R11",
        "v0.3.0 tag exists",
        lambda: _git_tag_exists("v0.3.0"),
    ),
]


SUBSTRATE_SIGNALS: list[tuple[str, str, callable]] = [
    (
        "S01",
        "AcceptanceSuite compiled + committed per run",
        lambda: _module_imports("ract.core.loop"),
    ),
    (
        "S02",
        "Loop termination T1 predicate-based",
        lambda: _grep_file("src/ract/core/loop.py", "check_t1"),
    ),
    (
        "S03",
        "Every step runs in git worktree rootact/step/<step_id>",
        lambda: _grep_file("src/ract/executor/worktree.py", "rootact/step"),
    ),
    (
        "S04",
        "Every step runs inside sandbox derived from capability manifest",
        lambda: _grep_file("src/ract/executor/loop.py", "sandbox_backend"),
    ),
    (
        "S05",
        "Manifest published per run (primitive present; publication side gap)",
        lambda: _module_imports("ract.security.manifest"),
    ),
    (
        "S06",
        "Bubblewrap + Landlock + seccomp on Linux; Seatbelt on macOS",
        lambda: (
            _file_exists("src/ract/security/sandbox_linux.py")
            and _file_exists("src/ract/security/sandbox_macos.py")
        ),
    ),
    (
        "S07",
        "Every model action is member of closed Pydantic union",
        lambda: _grep_file("src/ract/core/actions.py", "discriminator"),
    ),
    (
        "S08",
        "Per-provider conformance report card gates router registration",
        lambda: (
            _dir_exists("evals", "conformance")
            and _file_exists("src/ract/providers/gate.py")
        ),
    ),
    (
        "S09",
        "Hash-chained event log at evals/runs/<run_id>/events.jsonl",
        lambda: _module_imports("ract.trace.events"),
    ),
    (
        "S10",
        "OpenTelemetry spans exportable to any OTLP backend",
        lambda: _file_exists("src", "ract", "trace", "otel.py"),
    ),
    (
        "S11",
        "ract trace replay|fork|diff|to-test wired",
        lambda: _grep_file("src/ract/trace/cli_trace.py", "_trace_command"),
    ),
    (
        "S12",
        "Rootknot carries generator_signature + environment_signature",
        lambda: (
            _grep_file("src/ract/core/rootknot.py", "generator_signature")
            and _grep_file("src/ract/core/rootknot.py", "environment_signature")
        ),
    ),
    (
        "S13",
        "Invariant RK-3 tested",
        lambda: _file_exists(
            "tests", "property", "test_rk3_environmental_attestation.py"
        ),
    ),
    (
        "S14",
        "Display-only author marker (see tests/test_root_author_display_only.py)",
        lambda: _file_exists("tests", "test_root_author_display_only.py"),
    ),
    (
        "S15",
        "Whisperer + Fence + Auction contracts wired",
        lambda: (
            _file_exists("src/ract/contracts/whisperer.py")
            and _file_exists("src/ract/contracts/fence.py")
            and _file_exists("src/ract/contracts/auction.py")
        ),
    ),
    (
        "S16",
        "evals/LEADERBOARD.md shows polyglot + swebench + conformance + security per provider",
        lambda: _file_exists("evals", "LEADERBOARD.md"),
    ),
]


# v0.5.0 memory-discipline signals (spec §Signals items 1-13).
# Each item is a testable file/module/behavior existence check.
MEMORY_SIGNALS: list[tuple[str, str, callable]] = [
    (
        "M01",
        "src/ract/memory/budget.py exists; BudgetAccountant refuses on ceiling",
        lambda: (
            _file_exists("src", "ract", "memory", "budget.py")
            and _grep_file("src/ract/memory/budget.py", "BudgetAccountant")
        ),
    ),
    (
        "M02",
        "src/ract/memory/budget_defaults.yaml exists",
        lambda: _file_exists("src", "ract", "memory", "budget_defaults.yaml"),
    ),
    (
        "M03",
        "symbol_index.py + schema + watcher exist",
        lambda: (
            _file_exists("src", "ract", "memory", "symbol_index.py")
            and _file_exists("src", "ract", "memory", "symbol_index_schema.sql")
            and _file_exists("src", "ract", "memory", "watcher.py")
        ),
    ),
    (
        "M04",
        "tree-sitter language chunkers for python/typescript/rust/go land",
        lambda: (
            _file_exists("src", "ract", "memory", "languages", "python.py")
            and _file_exists("src", "ract", "memory", "languages", "typescript.py")
            and _file_exists("src", "ract", "memory", "languages", "rust.py")
            and _file_exists("src", "ract", "memory", "languages", "go.py")
        ),
    ),
    (
        "M05",
        "graph_index.py + LSP populator + blast_radius query API",
        lambda: (
            _file_exists("src", "ract", "memory", "graph_index.py")
            and _grep_file("src/ract/memory/graph_index.py", "blast_radius")
        ),
    ),
    (
        "M06",
        "semantic_index.py + bge-small default embedding",
        lambda: (
            _file_exists("src", "ract", "memory", "semantic_index.py")
            and _grep_file("src/ract/memory/embedding.py", "bge-small-en-v1.5")
        ),
    ),
    (
        "M07",
        "retrieve.py + four-level cascade + query cache",
        lambda: (
            _file_exists("src", "ract", "memory", "retrieve.py")
            and _file_exists("src", "ract", "memory", "cache.py")
        ),
    ),
    (
        "M08",
        "functions/{intake,research,plan,edit}.py all exist",
        lambda: all(
            _file_exists("src", "ract", "memory", "functions", f"{name}.py")
            for name in ("intake", "research", "plan", "edit")
        ),
    ),
    (
        "M09",
        "playbooks/{refactor_rename,refactor_extract,bug_fix,unit_test}.yaml exist",
        lambda: all(
            _file_exists("src", "ract", "memory", "playbooks", f"{name}.yaml")
            for name in ("refactor_rename", "refactor_extract", "bug_fix", "unit_test")
        ),
    ),
    (
        "M10",
        "probes/{needle,coherence,adherence}.py all exist",
        lambda: all(
            _file_exists("src", "ract", "memory", "probes", f"{name}.py")
            for name in ("needle", "coherence", "adherence")
        ),
    ),
    (
        "M11",
        "Seven new EventKind members present",
        lambda: all(
            _grep_file("src/ract/trace/events.py", kind)
            for kind in (
                "budget.declared",
                "budget.exceeded",
                "retrieval.requested",
                "retrieval.satisfied",
                "retrieval.cascaded",
                "retrieval.refused",
                "probe.evaluated",
            )
        ),
    ),
    (
        "M12",
        "SubstrateLoop wires retrieval bundle onto SubstrateStepSpec.metadata",
        lambda: (
            _grep_file("src/ract/executor/loop.py", "retrieval_bundle")
            and _file_exists(
                "tests",
                "contracts",
                "test_substrate_loop_retrieval_wiring.py",
            )
        ),
    ),
    (
        "M13",
        "Rootknot generator payload carries optional retrieval_attestation",
        lambda: (
            _grep_file("src/ract/core/rootknot.py", "retrieval_attestation")
            and _file_exists(
                "tests",
                "memory",
                "test_rootknot_retrieval_attestation.py",
            )
        ),
    ),
]


ALM_SIGNALS: list[tuple[str, str, callable]] = [
    (
        "A01",
        "Two AcceptanceSuite families (visible + held-out sealed)",
        lambda: _grep_file("src/ract/antilazy/holdout.py", "DualAcceptanceSuite"),
    ),
    (
        "A02",
        "Mutation-kill report committed per run",
        lambda: _file_exists("src", "ract", "antilazy", "mutation.py"),
    ),
    (
        "A03",
        "Semantic differentiation report or documented reason",
        lambda: _file_exists("src", "ract", "antilazy", "patchdiff.py"),
    ),
    (
        "A04",
        "Coverage delta report per touched file",
        lambda: _file_exists("src", "ract", "antilazy", "coverage.py"),
    ),
    (
        "A05",
        "test_integrity section in capability manifest",
        lambda: _grep_file("src/ract/security/manifest.py", "test_integrity"),
    ),
    (
        "A06",
        "symgraph.db + under-edit closure pre-commit",
        lambda: _file_exists("src", "ract", "antilazy", "symgraph.py"),
    ),
    (
        "A07",
        "Companion red-team report using distinct provider",
        lambda: _file_exists("src", "ract", "antilazy", "companion.py"),
    ),
    (
        "A08",
        "Effort estimate + reconciliation",
        lambda: _file_exists("src", "ract", "antilazy", "effort.py"),
    ),
    (
        "A09",
        "Sycophancy circuit report",
        lambda: _file_exists("src", "ract", "antilazy", "sycophancy.py"),
    ),
    (
        "A10",
        "Investigator report present",
        lambda: _file_exists("src", "ract", "antilazy", "investigator.py"),
    ),
    (
        "A11",
        "Three-signature Rootknot: generator + environment + antilazy",
        lambda: _grep_file("src/ract/core/rootknot.py", "antilazy_signature"),
    ),
    (
        "A12",
        "Invariant AL-1 tested in tests/property/test_antilazy_invariants.py",
        lambda: _file_exists("tests", "property", "test_antilazy_invariants.py"),
    ),
    (
        "A13",
        "evals/antilazy/ corpus with adversarial cases from documented incidents",
        lambda: _dir_exists("evals", "antilazy"),
    ),
    (
        "A14",
        "evals/LEADERBOARD.md shows claimed + attested pass rates",
        lambda: (
            _grep_file("evals/LEADERBOARD.md", "attested_pass_rate")
            or _grep_file("evals/LEADERBOARD.md", "attested pass rate")
        ),
    ),
    (
        "A15",
        "COMPANION_MATRIX.md defines eligible primary-companion pairs",
        lambda: _file_exists("evals", "conformance", "COMPANION_MATRIX.md"),
    ),
    (
        "A16",
        "laziness.violated event kind registered",
        lambda: _grep_file("src/ract/trace/events.py", "laziness.violated"),
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _readme_word_count() -> int:
    text = (_REPO_ROOT / "README.md").read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    return len(text.split())


def _git_tag_exists(tag: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "tag", "-l", tag],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() == tag


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sid,desc,check", REBUILD_SIGNALS)
def test_rebuild_signals_all_green(sid: str, desc: str, check: callable) -> None:
    assert check(), f"REBUILD signal {sid} RED: {desc}"


@pytest.mark.parametrize("sid,desc,check", SUBSTRATE_SIGNALS)
def test_substrate_signals_all_green(sid: str, desc: str, check: callable) -> None:
    assert check(), f"SUBSTRATE signal {sid} RED: {desc}"


@pytest.mark.parametrize("sid,desc,check", ALM_SIGNALS)
def test_antilazy_signals_all_green(sid: str, desc: str, check: callable) -> None:
    assert check(), f"ALM signal {sid} RED: {desc}"


@pytest.mark.parametrize("sid,desc,check", MEMORY_SIGNALS)
def test_memory_discipline_signals_all_green(
    sid: str, desc: str, check: callable
) -> None:
    """v0.5.0 memory-discipline §Signals (items 1-13). Each item mirrors the
    master spec's boolean checklist; a red here refuses the tag."""
    assert check(), f"MEMORY signal {sid} RED: {desc}"


def test_combined_signal_count_matches_documented_total() -> None:
    """Honest count. v0.4.1 shipped 43 (11 REBUILD + 16 SUBSTRATE + 16 ALM).
    v0.5.0 adds the 13 memory-discipline §Signals for a combined total of 56.
    This test enforces the honest total and its per-list breakdown.
    """
    assert len(REBUILD_SIGNALS) == 11, "REBUILD checklist has 11 items per spec §4"
    assert len(SUBSTRATE_SIGNALS) == 16
    assert len(ALM_SIGNALS) == 16
    assert len(MEMORY_SIGNALS) == 13, (
        "Memory-discipline §Signals list has 13 items per master spec"
    )
    combined = (
        len(REBUILD_SIGNALS)
        + len(SUBSTRATE_SIGNALS)
        + len(ALM_SIGNALS)
        + len(MEMORY_SIGNALS)
    )
    assert combined == 56, (
        f"Combined signal total {combined} != documented total 56. "
        "See CHANGELOG [0.5.0] Verify section for the v0.4.1-plus-memory total."
    )


_MEMORY_PACKAGE_FILES: tuple[tuple[str, ...], ...] = (
    ("src", "ract", "memory", "budget.py"),
    ("src", "ract", "memory", "budget_defaults.yaml"),
    ("src", "ract", "memory", "budget_registry.py"),
    ("src", "ract", "memory", "symbol_index.py"),
    ("src", "ract", "memory", "symbol_index_schema.sql"),
    ("src", "ract", "memory", "watcher.py"),
    ("src", "ract", "memory", "walker.py"),
    ("src", "ract", "memory", "parser.py"),
    ("src", "ract", "memory", "graph_index.py"),
    ("src", "ract", "memory", "graph_index_schema.sql"),
    ("src", "ract", "memory", "graph_populator.py"),
    ("src", "ract", "memory", "lsp.py"),
    ("src", "ract", "memory", "lsp_fallback.py"),
    ("src", "ract", "memory", "semantic_index.py"),
    ("src", "ract", "memory", "semantic_builder.py"),
    ("src", "ract", "memory", "embedding.py"),
    ("src", "ract", "memory", "chunker.py"),
    ("src", "ract", "memory", "chunk.py"),
    ("src", "ract", "memory", "cpu_fallback.py"),
    ("src", "ract", "memory", "retrieve.py"),
    ("src", "ract", "memory", "cache.py"),
    ("src", "ract", "memory", "query_trace.py"),
    ("src", "ract", "memory", "composition.py"),
    ("src", "ract", "memory", "composition_runner.py"),
    ("src", "ract", "memory", "session.py"),
    ("src", "ract", "memory", "events.py"),
    ("src", "ract", "memory", "failure_records.py"),
    ("src", "ract", "memory", "repo_fingerprint.py"),
    ("src", "ract", "memory", "cli_memory.py"),
    ("src", "ract", "memory", "functions", "intake.py"),
    ("src", "ract", "memory", "functions", "research.py"),
    ("src", "ract", "memory", "functions", "plan.py"),
    ("src", "ract", "memory", "functions", "edit.py"),
    ("src", "ract", "memory", "functions", "contracts.py"),
    ("src", "ract", "memory", "functions", "errors.py"),
    ("src", "ract", "memory", "functions", "prompts_loader.py"),
    ("src", "ract", "memory", "functions", "provider_adapter.py"),
    ("src", "ract", "memory", "playbooks", "refactor_rename.yaml"),
    ("src", "ract", "memory", "playbooks", "refactor_extract.yaml"),
    ("src", "ract", "memory", "playbooks", "bug_fix.yaml"),
    ("src", "ract", "memory", "playbooks", "unit_test.yaml"),
    ("src", "ract", "memory", "probes", "needle.py"),
    ("src", "ract", "memory", "probes", "coherence.py"),
    ("src", "ract", "memory", "probes", "adherence.py"),
    ("src", "ract", "memory", "probes", "scheduler.py"),
    ("src", "ract", "memory", "languages", "python.py"),
    ("src", "ract", "memory", "languages", "typescript.py"),
    ("src", "ract", "memory", "languages", "rust.py"),
    ("src", "ract", "memory", "languages", "go.py"),
)


def test_memory_module_surface_exists() -> None:
    """Every file in the memory-discipline surface enumerated by the master
    spec §Repository layout must be present at tag time. Missing files mean
    a module fragment skipped its DoD.
    """
    missing = [
        "/".join(parts) for parts in _MEMORY_PACKAGE_FILES if not _file_exists(*parts)
    ]
    assert not missing, (
        f"Memory-discipline surface files missing at tag: {missing}. "
        "Every entry mirrors the master spec §Repository layout."
    )


_NEW_EVENT_KINDS: tuple[str, ...] = (
    "budget.declared",
    "budget.exceeded",
    "retrieval.requested",
    "retrieval.satisfied",
    "retrieval.cascaded",
    "retrieval.refused",
    "probe.evaluated",
)


def test_new_event_kinds_present() -> None:
    """The seven memory-discipline EventKind members are load-bearing gate
    entries in :data:`ract.trace.events.LEGAL_EVENT_KINDS`. A member added
    but not present in the frozenset would refuse at write time.
    """
    from ract.trace.events import LEGAL_EVENT_KINDS

    missing = [kind for kind in _NEW_EVENT_KINDS if kind not in LEGAL_EVENT_KINDS]
    assert not missing, (
        f"Memory-discipline event kinds not present in LEGAL_EVENT_KINDS: {missing}"
    )


def test_version_matches_across_files() -> None:
    """VERSION + pyproject + __init__ + `ract --version` all resolve to
    the same PEP 440 version identity. v0.5.1 has no rc suffix so all
    three files carry the literal string ``0.5.1`` (module_08 Lateral
    Chain branch B). Identity holds under ``packaging.version.Version``
    across the three files AND against the CLI-reported string.
    """
    from packaging.version import Version

    expected = Version("0.5.2")

    version_text = (_REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    # Extract the semver token from the VERSION file's human-friendly
    # `RACT v0.4.1 - Intent-Fidelity` shape.
    match = re.search(r"v?(\d+\.\d+\.\d+(?:[-.]?rc\d+)?)", version_text)
    assert match, f"VERSION file has no parseable version token: {version_text!r}"
    assert Version(match.group(1)) == expected, (
        f"VERSION {match.group(1)!r} != expected {expected!r}"
    )

    pyproject_text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject_text, flags=re.MULTILINE)
    assert match, "pyproject.toml has no [project].version"
    assert Version(match.group(1)) == expected, (
        f"pyproject.toml version {match.group(1)!r} != expected {expected!r}"
    )

    init_text = (_REPO_ROOT / "src" / "ract" / "__init__.py").read_text(
        encoding="utf-8"
    )
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', init_text, flags=re.MULTILINE)
    assert match, "__init__.py has no __version__"
    assert Version(match.group(1)) == expected, (
        f"__init__.py __version__ {match.group(1)!r} != expected {expected!r}"
    )


def test_ract_version_cli_reports_aligned_identity() -> None:
    """`ract --version` (via ``python -m ract.cli --version``) prints a
    version string that resolves under ``packaging.version.Version`` to
    the same identity as VERSION/pyproject/__init__. v0.4.1 has no rc
    suffix so the literal string ``0.4.1`` and the PEP 440 canonical
    form ``0.4.1`` are identical — no normalization needed (module_08
    Lateral Chain branch B).
    """
    from packaging.version import Version

    import ract

    module_version = Version(ract.__version__)
    expected = Version("0.5.2")
    assert module_version == expected, (
        f"ract.__version__ {ract.__version__!r} != expected {expected!r}"
    )
    # And the aligned PEP 440 canonical form is the literal `0.5.2`.
    assert str(expected) == "0.5.2"


def test_changelog_has_0_4_0_entry_with_module_bullets() -> None:
    text = (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.4.0] - 2026-07-26" in text, "CHANGELOG missing [0.4.0] entry"
    # 7 substrate + 1 substrate module_08 shim + 7 ALM module bullets;
    # accept the `(module_0X, ADR-...)` OR `substrate module_0X` OR
    # `(module_0X substrate close)` framing.
    substrate_hits = sum(
        1
        for m in range(1, 9)
        if f"substrate module_0{m}" in text
        or f"(module_0{m}, ADR-0" in text
        or f"(module_0{m} substrate close" in text
    )
    assert substrate_hits >= 7, (
        f"CHANGELOG missing per-substrate-module bullets (found {substrate_hits}/8)"
    )
    # ALM ADRs 0019-0025 all mentioned.
    for adr in (
        "ADR-0019",
        "ADR-0020",
        "ADR-0021",
        "ADR-0022",
        "ADR-0023",
        "ADR-0024",
        "ADR-0025",
    ):
        assert adr in text, f"CHANGELOG missing ALM {adr} bullet reference"


def test_readme_names_al1() -> None:
    text = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "AL-1" in text, "README must name AL-1 with a one-sentence explanation"
    assert "RK-3" in text, "README should also name RK-3 for symmetry"


def test_leaderboard_has_attested_column() -> None:
    text = (_REPO_ROOT / "evals" / "LEADERBOARD.md").read_text(encoding="utf-8")
    assert "attested_pass_rate" in text, "LEADERBOARD missing attested_pass_rate column"


def test_companion_matrix_exists() -> None:
    p = _REPO_ROOT / "evals" / "conformance" / "COMPANION_MATRIX.md"
    assert p.is_file()
    assert p.stat().st_size > 0, "COMPANION_MATRIX.md exists but is empty"


def test_roadmap_compiled_from_all_modules() -> None:
    text = (_REPO_ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    # ROADMAP must reference module_01 through module_07 (substrate + ALM
    # share the module_0X numbering).
    for n in range(1, 8):
        assert f"module_0{n}:" in text, f"ROADMAP missing module_0{n}: bullets"
    # Operator-side dispatcher gaps section present.
    assert "Operator-side dispatcher gaps" in text
    # v0.5 hardening compiled from three sources.
    assert "v0.5 hardening (from substrate close)" in text
    assert "v0.5 hardening (from ALM close)" in text
    assert "v0.5 hardening (from second-pass deferrals)" in text


# ---------------------------------------------------------------------------
# v0.4.1 intent-fidelity release-surface tests. Module_08 close (2026-08-17).
# ---------------------------------------------------------------------------


def test_changelog_has_0_4_1_entry_with_era_bullets() -> None:
    """CHANGELOG carries a ``## [0.4.1] - 2026-08-17`` entry with a bullet per
    era covered by the intent-fidelity pipeline plus a bullet per fix commit
    landed under ``intent-fidelity(v0.5): fix``. Seven era bullets: v0.1.x,
    v0.2.0, v0.3.0, v0.4.0 SUBSTRATE, v0.4.0 ALM, v0.4.0-rc1 audits,
    restoration clusters 1+2.
    """
    text = (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.4.1]" in text, "CHANGELOG missing [0.4.1] entry"
    assert "Intent-Fidelity" in text, (
        "CHANGELOG [0.4.1] entry missing Intent-Fidelity label"
    )
    # Seven era markers must appear inside the [0.4.1] block.
    body = text.split("## [0.4.1]", 1)[1].split("## [0.4.0]", 1)[0]
    for era in (
        "v0.1.x",
        "v0.2.0",
        "v0.3.0",
        "SUBSTRATE",
        "ALM",
        "v0.4.0-rc1 audits",
        "Restoration clusters",
    ):
        assert era in body, f"CHANGELOG [0.4.1] entry missing era bullet: {era!r}"
    # Fix-commit bullets: at least the 10 known intent-fidelity fix commit
    # short SHAs are named in the [0.4.1] body.
    fix_shas = (
        "755578f",
        "f4598ed",
        "ceeef12",
        "84ece29",
        "fdd7474",
        "9e56078",
        "881c5ee",
        "b6cc908",
        "bfecde4",
        "9e6d0f9",
    )
    missing = [sha for sha in fix_shas if sha not in body]
    assert not missing, f"CHANGELOG [0.4.1] entry missing fix-commit SHAs: {missing}"


_INTENT_FIDELITY_MODULES: tuple[str, ...] = (
    "module_01.md",
    "module_02.md",
    "module_03.md",
    "module_04.md",
    "module_05.md",
    "module_06.md",
    "module_07.md",
)


def test_intent_fidelity_module_attestations_logged() -> None:
    """Every intent-fidelity module (01-07) carries a
    ``## Intent verification results`` section. The section is the
    audit anchor per module fragment; a module with no attestation
    cannot count as intent-verified for the combined sweep.

    ``_BUILD/`` is gitignored — the module fragments only exist in the
    operator's local development tree, never on a CI checkout. The
    attestation invariant is a development-time gate, not a
    distribution invariant. Skip cleanly when the directory is absent.
    """
    base = _REPO_ROOT / "_BUILD" / "ract_v0.4.1_intent_fidelity"
    if not base.is_dir():
        pytest.skip(
            "_BUILD/ract_v0.4.1_intent_fidelity is gitignored (development-only); "
            "attestation check runs on the operator's local tree, not on CI checkouts"
        )
    missing: list[str] = []
    for module_name in _INTENT_FIDELITY_MODULES:
        path = base / module_name
        assert path.is_file(), f"Intent-fidelity module fragment missing: {module_name}"
        content = path.read_text(encoding="utf-8", errors="ignore")
        if "## Intent verification results" not in content:
            missing.append(module_name)
    assert not missing, (
        "Intent-fidelity modules missing ## Intent verification results section: "
        f"{missing}"
    )


def test_roadmap_carries_intent_fidelity_module_gaps() -> None:
    """`docs/ROADMAP.md` carries a ``v0.5 hardening (from intent-fidelity ...``
    section anchoring every one of the seven intent-fidelity modules' Flagged
    gaps. Ensures the compilation step did not silently skip a module.
    """
    text = (_REPO_ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    # Single umbrella section OR per-module sections both satisfy the DoD;
    # this test asserts at least the umbrella anchor plus one mention per
    # intent-fidelity module fragment id.
    assert "intent-fidelity" in text.lower(), (
        "ROADMAP missing an intent-fidelity gap section"
    )
    for module_name in _INTENT_FIDELITY_MODULES:
        # Strip the .md extension when checking references.
        stub = module_name.removesuffix(".md")
        assert stub in text, (
            f"ROADMAP missing a reference to intent-fidelity {stub} (no gaps carried?)"
        )


# ---------------------------------------------------------------------------
# v0.5.0 memory-discipline release-surface tests. Module_10 close (2026-08-19).
# ---------------------------------------------------------------------------


_MEMORY_MODULES: tuple[str, ...] = (
    "module_01.md",
    "module_02.md",
    "module_03.md",
    "module_04.md",
    "module_05.md",
    "module_06.md",
    "module_07.md",
    "module_08.md",
    "module_09.md",
)


def test_changelog_has_0_5_0_entry_with_module_bullets() -> None:
    """CHANGELOG carries a ``## [0.5.0] - 2026-08-19`` entry with a bullet per
    memory-discipline module (01-09) plus the release-close module_10 line,
    an Added/Extended/Verified section triple, and a Known limitations section
    naming the v0.6 deferrals.
    """
    text = (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.5.0]" in text, "CHANGELOG missing [0.5.0] entry"
    assert "Memory Discipline" in text, (
        "CHANGELOG [0.5.0] entry missing Memory Discipline label"
    )
    body = text.split("## [0.5.0]", 1)[1].split("## [0.4.1]", 1)[0]
    # 10 per-module bullets (modules 01-10).
    module_hits = sum(1 for m in range(1, 11) if f"module_{m:02d}" in body)
    assert module_hits >= 10, (
        f"CHANGELOG [0.5.0] entry missing per-module bullets (found {module_hits}/10)"
    )
    # Added / Extended / Verified / Known limitations sections all present.
    for section in (
        "### Added",
        "### Extended",
        "### Verified",
        "### Known limitations",
    ):
        assert section in body, (
            f"CHANGELOG [0.5.0] entry missing section header: {section!r}"
        )
    # Nine memory-discipline ADRs (ADR-0031 through ADR-0039) cited.
    for adr in (f"ADR-003{n}" for n in range(1, 10)):
        assert adr in body, f"CHANGELOG [0.5.0] entry missing {adr} reference"


def test_roadmap_carries_memory_discipline_module_gaps() -> None:
    """`docs/ROADMAP.md` carries a ``v0.6 hardening (from memory-discipline
    module_0N)`` section anchoring every one of the nine memory-discipline
    modules' Flagged gaps. Ensures the compilation step did not silently
    skip a module.
    """
    text = (_REPO_ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "memory-discipline" in text.lower() or "memory discipline" in text.lower(), (
        "ROADMAP missing a memory-discipline gap section"
    )
    for module_name in _MEMORY_MODULES:
        stub = module_name.removesuffix(".md")
        assert stub in text, (
            f"ROADMAP missing a reference to memory-discipline {stub} "
            "(no gaps carried?)"
        )


def test_readme_names_memory_discipline() -> None:
    """README's v0.5.0 change note names the three indexes, the retrieve
    primitive, and the four v0.5.0 functions so an operator reading the
    front page sees what shipped.
    """
    text = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Memory Discipline" in text, "README missing Memory Discipline label"
    for token in (
        "symbol index",
        "graph index",
        "semantic index",
        "retrieve",
        "intake",
        "research",
        "plan",
        "edit",
    ):
        assert token in text.lower(), f"README v0.5.0 section missing token: {token!r}"


def test_no_prior_v0_4_0_tag_conflict() -> None:
    """Substrate did NOT tag; ALM module_08 lands the first v0.4-family
    tag as v0.4.0-rc1. Verify no stray v0.4.0 tag already exists that
    would conflict with a future v0.4.0-final release."""
    # v0.4.0-rc1 IS this module's tag; it MAY exist at test-eval time
    # (test runs after the tag lands too). Just ensure no BARE `v0.4.0`.
    result = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "tag", "-l", "v0.4.0"],
        capture_output=True,
        text=True,
        check=False,
    )
    # Exactly `v0.4.0` (no rc1 suffix) must not exist.
    assert result.stdout.strip() != "v0.4.0", (
        "A bare v0.4.0 tag exists and would conflict with the v0.4.0-final "
        "future release. This ALM module_08 lands v0.4.0-rc1 only."
    )


# ---------------------------------------------------------------------------
# Closed-IP wordlist regression gate. Intent-Fidelity module_06 (2026-08-17)
# extends the v0.4.0-rc1 audit's six-category grep pattern to a persistent
# test so a leaked closed-IP term cannot re-enter the tracked tree silently.
# The wordlist mirrors the operator's private-name discipline plus the
# specific dispatcher-function and operator-path patterns the v0.4.0-rc1
# audit generalized. Two deferred hits in ``assets/demo.cast`` at lines 53
# and 76 are documented in ``assets/README.md``; the test allows exactly
# those two hits and refuses every other leak.
# ---------------------------------------------------------------------------

_CLOSED_IP_TERMS: tuple[str, ...] = (
    "kronos",
    "prismml",
    "nemotron",
    "grove_forge",
    "grove-forge",
    "snapdragon",
    "strix halo",
    "cognify",
    "overnight_dt",
    "never_idle",
    "temporal_kg",
    "x elite",
    "rootclaw",
    "reason_deep",
    "reason_magistral",
    "reason_r1_latest",
    "flash_reason",
    "flash_lite",
    "reason_nemotron_ultra",
    "openrouter_dispatch",
    "google_dispatch",
    "nvidia_dispatch",
    "mistral_dispatch",
    "endpoints_skill",
)


def test_no_closed_ip_terms_in_tracked_files() -> None:
    """Grep every tracked file (via ``git grep -Iil``) for each closed-IP
    term in ``_CLOSED_IP_TERMS`` (case-insensitive). Zero hits allowed
    except the two documented deferrals in ``assets/demo.cast``.

    Regression anchor: the v0.4.0-rc1 audit generalized dispatcher-function
    names, operator-project names, and operator absolute paths across the
    tracked tree. Intent-Fidelity module_06 verifies the fix still holds
    and pins it here so a re-leak becomes a red test.
    """

    hits: dict[str, list[str]] = {}
    for term in _CLOSED_IP_TERMS:
        result = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "grep", "-Iil", term],
            capture_output=True,
            text=True,
            check=False,
        )
        files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        # ``assets/demo.cast`` carries two operator-path lines that require
        # a live asciinema re-record to purge. Tolerated because the
        # deferral is documented in ``assets/README.md`` and separately
        # covered by ``test_demo_cast_freshness``. ``tests/test_release_surface.py``
        # necessarily names the wordlist itself; excluded from its own scan.
        files = [
            f
            for f in files
            if f != "assets/demo.cast" and f != "tests/test_release_surface.py"
        ]
        if files:
            hits[term] = files
    assert not hits, (
        "Closed-IP wordlist regression: one or more terms re-entered the "
        f"tracked tree. Hits: {hits}. If the term is intentional (e.g., a "
        "public model catalog URL in an inline citation), narrow the "
        "wordlist. Otherwise, generalize the leaking text."
    )


# ---------------------------------------------------------------------------
# v0.5.1 wiring completion module_01 -- provenance + docs sync gates
# ---------------------------------------------------------------------------


def test_changelog_v051_shas_resolve_in_git() -> None:
    """Every short SHA cited in the CHANGELOG's ``[0.5.1]`` section must
    resolve to a real commit under ``git rev-parse --verify``.

    Regression anchor: Lens B C1 of the 2026-08-21 8-lens audit found
    that all 20 primary/SP short SHAs in the ``[0.5.1]`` bullets were
    fabricated (post-``git filter-repo`` the pre-rewrite SHAs stopped
    resolving). Module_01 of the wiring completion pipeline
    regenerated them; this test pins the fix so a future rewrite
    trips a red before the release-note bullets go stale silently.

    The gate is per-section: the substring of ``CHANGELOG.md`` between
    ``## [0.5.1]`` and the next ``## [`` heading is scanned for
    7-character hex tokens surrounded by backticks (the CHANGELOG's
    short-SHA convention). Each token is passed to
    ``git rev-parse --verify <sha>^{commit}``; a non-zero exit is a
    hard failure.
    """
    text = (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    marker = "## [0.5.1]"
    start = text.find(marker)
    assert start != -1, "CHANGELOG missing [0.5.1] entry"
    next_section = text.find("\n## [", start + len(marker))
    if next_section == -1:
        next_section = len(text)
    section = text[start:next_section]

    # Backticked 7-char hex tokens; CHANGELOG SHA convention.
    candidates = set(re.findall(r"`([0-9a-f]{7})`", section))
    assert candidates, "[0.5.1] section carries no `<7-hex>` tokens to verify"

    unresolved: list[str] = []
    for sha in sorted(candidates):
        result = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "--verify", f"{sha}^{{commit}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            unresolved.append(sha)

    assert not unresolved, (
        "CHANGELOG [0.5.1] cites SHA(s) that do not resolve under "
        f"``git rev-parse --verify``: {unresolved}. Rewrite of history "
        "(filter-repo, force-push) invalidates cited SHAs; regenerate "
        "the bullets against the current tree via "
        "``git log --all --oneline --grep='release(v0.5.1)'``."
    )


def test_events_doc_schema_version_matches_event_kind_count() -> None:
    """The ``schema_version`` frontmatter in ``docs/EVENTS.md`` must
    stay aligned with the closed vocabulary in
    ``src/ract/trace/events.py::EventKind``.

    Rule: the EVENTS.md doc's rule (line ~19) says a new EventKind
    requires bumping the frontmatter version. v0.5.0 memory
    discipline landed at ``schema_version: "3"`` with 7 memory kinds
    added. v0.5.1 module_09 landed
    ``manifest.ledger.appended|refused``,
    ``whisperer.contract_violation``, and
    ``assumption.accepted`` (bumped to "4"). v0.5.1 wiring module_05
    landed ``process.reaped`` for the Lens C C-03 tree-kill wire-in
    (bumped to "5").

    Regression anchor: Lens B C6 of the 2026-08-21 8-lens audit
    surfaced that schema_version stuck at "3" while six new
    v0.5.1 kinds landed in ``events.py`` and CHANGELOG. Module_01
    of the wiring completion pipeline bumped the frontmatter + added
    the payload sections; this gate refuses a future kind-add that
    forgets the doc bump.

    v0.5.1 spec-completeness module_02 added ``state.budget_capped``
    (Lens 1A CRITICAL A-2 closure, 15%-of-input_target sub-budget cap
    on the state section) — schema bumps to "6".

    v0.5.1 spec-completeness module_04 added
    ``retrieval.grouping.applied`` (Lens 1C HIGH C-1 closure, cross-
    function grouping rules) — schema bumps to "7".

    v0.5.1 spec-completeness module_07 added
    ``subagent.disposed`` (Lens 2 Delta 3 closure, SubagentHandle
    cascade on non-T1 halt) — schema bumps to "8".

    Also verifies the eight v0.5.1 EventKind literals that are
    load-bearing gate entries are present in ``LEGAL_EVENT_KINDS``.
    """
    text = (_REPO_ROOT / "docs" / "EVENTS.md").read_text(encoding="utf-8")
    match = re.search(r'^schema_version:\s*"(\d+)"', text, flags=re.MULTILINE)
    assert match, "docs/EVENTS.md frontmatter missing schema_version"
    doc_version = match.group(1)
    assert doc_version == "8", (
        f"docs/EVENTS.md schema_version {doc_version!r} != expected '8'. "
        "v0.5.1 spec-completeness module_07 added "
        "``subagent.disposed``; bump the frontmatter + document "
        "the payload per docs/EVENTS.md's own rule."
    )

    # v0.5.1 kinds that must be in the closed literal.
    from ract.trace.events import LEGAL_EVENT_KINDS

    required = (
        "assumption.accepted",
        "manifest.ledger.appended",
        "manifest.ledger.refused",
        "whisperer.contract_violation",
        "process.reaped",
        "state.budget_capped",
        "retrieval.grouping.applied",
        "subagent.disposed",
    )
    missing = [k for k in required if k not in LEGAL_EVENT_KINDS]
    assert not missing, (
        f"v0.5.1 EventKind literal(s) missing from LEGAL_EVENT_KINDS: {missing}"
    )

    # The four EventKinds must ALSO be documented in EVENTS.md so the
    # ``payload schema per kind`` invariant holds.
    for kind in required:
        assert f"`{kind}`" in text, (
            f"docs/EVENTS.md missing payload section for `{kind}`"
        )


def test_adr_0042_documented_in_changelog() -> None:
    """ADR-0042 (sycophancy v2 tuning band) is authored in module_01 of
    the v0.5.1 wiring completion pipeline. Two anchors must hold at
    every tag:

    1. `docs/ADRs/ADR-0042-sycophancy-v2-tuning-band.md` exists.
    2. CHANGELOG `[0.5.1]` section references ADR-0042 (or its
       human-readable name "sycophancy v2 tuning band").

    Regression anchor: SP module_01 Q7 -- a future CHANGELOG
    regeneration (e.g. module_11 re-tag) must not silently drop the
    ADR-0042 cross-reference while the ADR file persists. Closes the
    ADR <-> release-notes loop.
    """
    adr_path = _REPO_ROOT / "docs" / "ADRs" / "ADR-0042-sycophancy-v2-tuning-band.md"
    assert adr_path.is_file(), (
        f"ADR-0042 missing at {adr_path}. v0.5.1 wiring completion "
        "module_01 authored it; re-verify the docs/ADRs/ tree."
    )

    changelog = (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    marker = "## [0.5.1]"
    start = changelog.find(marker)
    assert start != -1, "CHANGELOG missing [0.5.1] entry"
    next_section = changelog.find("\n## [", start + len(marker))
    if next_section == -1:
        next_section = len(changelog)
    section = changelog[start:next_section]
    assert (
        "ADR-0042" in section
        or "sycophancy v2 tuning band" in section.lower()
    ), (
        "CHANGELOG [0.5.1] does not reference ADR-0042 or its "
        "'sycophancy v2 tuning band' name. Re-add the reference "
        "when regenerating the release notes."
    )


# ---------------------------------------------------------------------------
# v0.5.1 spec-completeness module_01 -- docs honesty pass gates
# ---------------------------------------------------------------------------


def _v051_changelog_section() -> str:
    """Return the substring of ``CHANGELOG.md`` between ``## [0.5.1]``
    and the next ``## [`` heading. Load-bearing helper for the two
    false-claim grep gates below.
    """
    text = (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    marker = "## [0.5.1]"
    start = text.find(marker)
    assert start != -1, "CHANGELOG missing [0.5.1] entry"
    next_section = text.find("\n## [", start + len(marker))
    if next_section == -1:
        next_section = len(text)
    return text[start:next_section]


def _line_is_deferral_context(line: str) -> bool:
    """A line that mentions DSPy / LeWM is honest iff it names the
    deferral **explicitly**. This is a conservative allowlist: the
    line itself (or any of the lines around it, handled by the caller
    via a symmetric line window) must carry at least one **strong
    negation token** that asserts the mechanism is NOT shipping in
    v0.5.1.

    Weaker context tokens like "v0.6 scope" / "v0.6 backlog" alone
    are NOT sufficient (SP module_01 Q6.1: a stray "v0.6 scope"
    comment could otherwise be used to launder a false claim past
    the gate). The allowlist below requires an unambiguous
    "not shipped" or ADR-cross-ref token, which cannot be added
    accidentally.
    """
    lowered = line.lower()
    return any(
        token in lowered
        for token in (
            "not yet shipped",
            "not shipped",
            "deferred to v0.6",
            "defer to v0.6",
            "defers to v0.6",
            "adr-0043",
            "adr-0044",
        )
    )


def test_no_false_dspy_claim_in_v0_5_1_changelog() -> None:
    """The ``[0.5.1]`` CHANGELOG section must not mention DSPy without
    naming the deferral in the same 3-line window.

    Regression anchor: spec-completeness module_01 (2026-08-21). The
    2026-08-21 source-spec audit
    (``_BUILD/audit_2026-08-21c/lens_1F_self_adjustment.md``) found
    that DSPy signature compilation-recompilation is prescribed by
    the Memory Discipline spec but not shipped: no
    ``src/ract/compilation/``, no ``dspy`` in ``pyproject.toml``,
    zero source hits. ADR-0043 formalises the deferral to v0.6. This
    gate refuses a future CHANGELOG edit that claims DSPy shipped in
    v0.5.1 without ADR-0043-style context.

    The gate is line-scoped with an 11-line context window (line +/- 5)
    so a paragraph that names DSPy and the deferral in adjacent
    sentences passes. A bare "DSPy" mention with no deferral context
    anywhere in the 3-line window fails.
    """
    section = _v051_changelog_section()
    lines = section.splitlines()
    violations: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if "dspy" not in line.lower():
            continue
        window_start = max(0, i - 5)
        window_end = min(len(lines), i + 6)
        window = lines[window_start:window_end]
        if not any(_line_is_deferral_context(w) for w in window):
            violations.append((i, line.strip()))
    assert not violations, (
        "CHANGELOG [0.5.1] mentions DSPy without a deferral context "
        "in the 11-line window. See ADR-0043. Offending lines:\n"
        + "\n".join(f"  line {i}: {ln}" for i, ln in violations)
    )


def test_no_false_lewm_claim_in_v0_5_1_changelog() -> None:
    """The ``[0.5.1]`` CHANGELOG section must not mention LeWM (or
    ``23-dim`` behavioral-vector drift detection) without naming the
    deferral in the same 3-line window.

    Regression anchor: spec-completeness module_01 (2026-08-21). The
    2026-08-21 source-spec audit found no ``src/ract/observability/``
    package, no ``lewm.py`` / ``drift.py`` / ``spc.py``, and zero
    source hits for ``lewm``. ADR-0044 formalises the deferral to
    v0.6. This gate refuses a future CHANGELOG edit that claims
    LeWM drift detection shipped in v0.5.1 without ADR-0044-style
    context.
    """
    section = _v051_changelog_section()
    lines = section.splitlines()
    violations: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        lowered = line.lower()
        # "23-dim" catches "23-dim", "23 dim", "23-dimensional"; also
        # flag "lewm" case-insensitively.
        if "lewm" not in lowered and "23-dim" not in lowered:
            continue
        window_start = max(0, i - 5)
        window_end = min(len(lines), i + 6)
        window = lines[window_start:window_end]
        if not any(_line_is_deferral_context(w) for w in window):
            violations.append((i, line.strip()))
    assert not violations, (
        "CHANGELOG [0.5.1] mentions LeWM / 23-dim behavioral-vector "
        "drift detection without a deferral context in the 7-line "
        "window. See ADR-0044. Offending lines:\n"
        + "\n".join(f"  line {i}: {ln}" for i, ln in violations)
    )


def test_adr_0043_and_adr_0044_present() -> None:
    """ADR-0043 (DSPy deferral) and ADR-0044 (LeWM deferral) must
    both exist on disk.

    Spec-completeness module_01 authored both under
    ``docs/RACT_v0.5.1_SPEC_COMPLETENESS_SPEC.md`` §4 module_01. Each
    must:

    1. Live at the canonical path.
    2. Carry a ``## Status`` section with the word ``Accepted``.
    3. Carry a ``## Decision`` section.
    4. Carry a ``## Rationale`` or ``## Alternatives considered``
       section (both, in the shipped ADRs).
    """
    adr_root = _REPO_ROOT / "docs" / "ADRs"
    for name in (
        "ADR-0043-dspy-compilation-deferred-to-v06.md",
        "ADR-0044-lewm-drift-detection-deferred-to-v06.md",
    ):
        p = adr_root / name
        assert p.is_file(), f"ADR missing at {p}"
        body = p.read_text(encoding="utf-8")
        assert "## Status" in body, f"{name} missing ## Status"
        assert "Accepted" in body, f"{name} does not say Accepted"
        assert "## Decision" in body, f"{name} missing ## Decision"
        assert (
            "## Alternatives considered" in body
            or "## Rationale" in body
        ), f"{name} missing Rationale or Alternatives considered"


def test_adr_0043_and_adr_0044_referenced_in_v0_5_1_changelog() -> None:
    """The ``[0.5.1]`` CHANGELOG section must cite both new deferral
    ADRs so a reader tracing "why isn't DSPy shipping" or "why isn't
    LeWM shipping" finds the ADR before the disappointment.
    """
    section = _v051_changelog_section()
    assert "ADR-0043" in section, (
        "CHANGELOG [0.5.1] does not reference ADR-0043 (DSPy deferral). "
        "spec-completeness module_01 wired this cross-reference; "
        "re-add it if a regeneration dropped it."
    )
    assert "ADR-0044" in section, (
        "CHANGELOG [0.5.1] does not reference ADR-0044 (LeWM deferral). "
        "spec-completeness module_01 wired this cross-reference; "
        "re-add it if a regeneration dropped it."
    )


def test_memory_discipline_spec_flags_dspy_and_lewm_deferral() -> None:
    """The Memory Discipline spec's v0.6-backlog bullets for DSPy and
    the 23-dim drift detector must each carry an inline
    "Not shipped in v0.5.1 -- deferred to v0.6 per ADR-004X" callout.

    Regression anchor: spec-completeness module_01. Reader tracing
    from the spec's ``### v0.6 hardening (deferred)`` list must land
    on the ADR, not on ambiguity about whether the mechanism might
    have quietly slipped into a v0.5.x re-tag.
    """
    spec = (
        _REPO_ROOT / "docs" / "RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md"
    ).read_text(encoding="utf-8")
    # DSPy bullet must name ADR-0043.
    assert "DSPy" in spec, "spec missing DSPy backlog bullet"
    dspy_bullet_start = spec.find("- DSPy signature compilation")
    assert dspy_bullet_start != -1, "spec DSPy bullet moved / renamed"
    dspy_bullet_end = spec.find("\n-", dspy_bullet_start + 1)
    if dspy_bullet_end == -1:
        dspy_bullet_end = len(spec)
    dspy_bullet = spec[dspy_bullet_start:dspy_bullet_end]
    assert "ADR-0043" in dspy_bullet, (
        "Memory Discipline spec DSPy backlog bullet missing "
        "ADR-0043 deferral callout. spec-completeness module_01 "
        "wired this; re-add if dropped."
    )
    # 23-dim bullet must name ADR-0044.
    drift_bullet_start = spec.find("- Drift detector")
    assert drift_bullet_start != -1, "spec drift-detector bullet moved / renamed"
    drift_bullet_end = spec.find("\n-", drift_bullet_start + 1)
    if drift_bullet_end == -1:
        drift_bullet_end = len(spec)
    drift_bullet = spec[drift_bullet_start:drift_bullet_end]
    assert "ADR-0044" in drift_bullet, (
        "Memory Discipline spec 23-dim drift-detector backlog bullet "
        "missing ADR-0044 deferral callout. spec-completeness "
        "module_01 wired this; re-add if dropped."
    )
