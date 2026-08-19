"""Tests for the dead-code auction."""

from __future__ import annotations


import os
import time
from pathlib import Path
from unittest.mock import patch

from ract.cli import main
from ract.dead_code_auction import AuctionItem, DeadCodeAuction


def _set_old_mtime(path: Path, days: int = 200) -> None:
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def test_auction_finds_unreferenced_old_file(tmp_path: Path):
    target = tmp_path / "old_module.py"
    target.write_text("def unused():\n    pass\n", encoding="utf-8")
    _set_old_mtime(target)

    items = DeadCodeAuction(tmp_path).scan()

    assert len(items) == 1
    assert items[0].relative_path == "old_module.py"
    assert items[0].inbound_references == 0
    assert items[0].last_modified_days >= 200


def test_auction_ignores_recent_files(tmp_path: Path):
    target = tmp_path / "recent.py"
    target.write_text("def fresh():\n    pass\n", encoding="utf-8")

    items = DeadCodeAuction(tmp_path).scan()

    assert items == []


def test_auction_ignores_referenced_files(tmp_path: Path):
    old = tmp_path / "old_module.py"
    old.write_text("def helper():\n    pass\n", encoding="utf-8")
    _set_old_mtime(old)
    user = tmp_path / "user.py"
    user.write_text("from old_module import helper\n\nhelper()\n", encoding="utf-8")
    _set_old_mtime(user, days=10)

    items = DeadCodeAuction(tmp_path).scan()

    assert all(item.relative_path != "old_module.py" for item in items)


def test_auction_respects_min_age_days(tmp_path: Path):
    target = tmp_path / "middle_aged.py"
    target.write_text("def maybe():\n    pass\n", encoding="utf-8")
    _set_old_mtime(target, days=100)

    assert DeadCodeAuction(tmp_path, config={"min_age_days": 90}).scan()
    assert not DeadCodeAuction(tmp_path, config={"min_age_days": 120}).scan()


def test_auction_ignores_test_files_by_default(tmp_path: Path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    target = tests_dir / "test_x.py"
    target.write_text("def test_x():\n    pass\n", encoding="utf-8")
    _set_old_mtime(target)

    assert DeadCodeAuction(tmp_path).scan() == []
    items = DeadCodeAuction(tmp_path, config={"include_tests": True}).scan()
    assert len(items) == 1
    assert items[0].relative_path == str(Path("tests/test_x.py"))


def test_auction_ignores_dependency_dirs(tmp_path: Path):
    venv = tmp_path / ".venv" / "Lib" / "site-packages"
    venv.mkdir(parents=True)
    target = venv / "old_pkg.py"
    target.write_text("x = 1\n", encoding="utf-8")
    _set_old_mtime(target)

    items = DeadCodeAuction(tmp_path).scan()
    assert items == []


def test_auction_flags_module_imported_only_by_its_test(tmp_path: Path):
    """A production module referenced only by its paired test is still dead."""
    prod = tmp_path / "prod_module.py"
    prod.write_text("def helper():\n    pass\n", encoding="utf-8")
    _set_old_mtime(prod)

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_prod_module.py"
    test_file.write_text(
        "from prod_module import helper\n\ndef test_helper():\n    helper()\n",
        encoding="utf-8",
    )
    _set_old_mtime(test_file)

    items = DeadCodeAuction(tmp_path).scan()
    paths = [item.relative_path for item in items]
    assert "prod_module.py" in paths
    assert all("test_" not in p for p in paths)


def test_cli_auction_list_json(capsys, tmp_path: Path):
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")

    fake_item = AuctionItem(
        path=tmp_path / "dead.py",
        relative_path="dead.py",
        last_modified_days=250,
        inbound_references=0,
        reason="no inbound references",
    )

    with patch("ract.cli.DeadCodeAuction") as MockAuction:
        MockAuction.return_value.scan.return_value = [fake_item]
        code = main(["auction", "list", "--json", "--config", str(config)])
        out = capsys.readouterr().out

    assert code == 0
    assert "dead.py" in out
    assert "250" in out


def test_ract_auction_reports_zero_dead_modules():
    """Release gate: the RACT source tree must not accumulate dead modules.

    This test runs the auction against RACT itself. If it fails, the offending
    module(s) must either be wired back into production code, moved to an
    allowlist, or removed. Entry-point modules under ``eval/`` are allowed
    because they are invoked as scripts rather than imported.
    """
    project_root = Path(__file__).parent.parent / "src" / "ract"
    allowlist = set(DeadCodeAuction.DEFAULT_ALLOWLIST)
    allowlist.add("runner.py")
    # v0.4 (module_02): the substrate step-loop lives at
    # ``src/ract/executor/loop.py``. It is imported explicitly by
    # ``tests/property/test_transaction_atomicity.py`` and by
    # ``src/ract/cli.py`` (session ls / diff) but NOT re-exported from
    # ``ract/executor/__init__.py`` because doing so would trigger a
    # circular import (executor → core.loop → loop_planner → harness →
    # executor). The auction sees no inbound production reference;
    # allowlist here mirrors the pattern used for other transitional
    # substrate modules until module_03+ wires the substrate into the
    # live loop.
    allowlist.add("loop.py")
    # v0.4 (module_03): the platform-specific sandbox backends
    # (sandbox_linux, sandbox_macos) are lazily imported by
    # ``ract.security.sandbox.resolve_backend`` at runtime — the local
    # import keeps a missing macOS-only or Linux-only import from
    # crashing the wrong platform at package init time. The auction
    # cannot see through the lazy import, so both are allowlisted here
    # (same pattern as ``loop.py`` above).
    allowlist.add("sandbox_linux.py")
    allowlist.add("sandbox_macos.py")
    # v0.4 (module_04): the router gate is called from the SubstrateLoop
    # provider-selection path (which module_08 will land as the shipped
    # CLI default; today it is exercised through the conformance-gate
    # tests). It is exported from ``ract.providers.__init__`` and
    # imported by tests, but no v0.4 production call site imports it
    # directly — the plan says module_08 is where that wiring lands.
    # Allowlist mirrors the transitional-substrate pattern used above.
    allowlist.add("gate.py")
    # v0.4 (module_05): the OTLP mirror in ``ract.trace.otel`` uses lazy
    # local imports (opentelemetry-api / sdk / exporter-otlp are runtime
    # deps declared in pyproject.toml per ADR-0015) so the module
    # imports cleanly without live OTLP installed at test time. It is
    # exported from ``ract.trace.__init__`` and installed via
    # ``install_otlp_exporter`` from a shipped CLI code path lands in
    # module_08. Allowlist here mirrors the transitional-substrate
    # pattern used above until module_08 wires the run-entry install.
    allowlist.add("otel.py")
    # v0.4 (module_06): the environment-enforced contract primitives at
    # ``ract.contracts.{whisperer,fence,auction}`` and the sandbox key
    # module at ``ract.security.keys`` are exported from their package
    # __init__ files and consumed by tests today. The shipped CLI
    # migration to the environment-enforced call sites lands in
    # module_08 (the CLI wrappers ``ract whisper|fence|auction`` still
    # route through the v0.3 modules). Allowlist mirrors the
    # transitional-substrate pattern used above until module_08 wires
    # the SubstrateLoop-as-default path.
    allowlist.add("whisperer.py")
    allowlist.add("fence.py")
    # ``contracts/auction.py`` shares its filename with the executor's
    # auction — allowlist the basename to cover the new module. (The
    # v0.3 dead_code_auction.py already lives in the DEFAULT_ALLOWLIST.)
    allowlist.add("auction.py")
    # ``security/keys.py`` — SandboxKey generator; consumed by
    # module_06 tests and by the RK-3 verify path. No shipped-CLI call
    # site until module_08 (see module_06 Flagged gaps).
    allowlist.add("keys.py")
    # ALM module_01: ``antilazy/pre_commit.py`` is the G2 pre-commit
    # gate that the loop calls before a ``StepTransaction`` commits.
    # No shipped-CLI call site until ALM module_08 wires the pre-commit
    # entry point (see module_01 Flagged gaps).
    allowlist.add("pre_commit.py")
    # ALM module_05: ``antilazy/sycophancy.py`` and
    # ``antilazy/investigator.py`` land the sycophancy circuit and the
    # Investigator pre-completion contract respectively;
    # ``security/alm_verifier_key.py`` lands the ALM verifier signing
    # key type. All three are consumed by
    # ``tests/test_antilazy_al1.py`` and by the eventual LoopController
    # wiring that module_08 lands. Allowlisted mirroring the
    # module_06 substrate pattern.
    allowlist.add("sycophancy.py")
    allowlist.add("investigator.py")
    allowlist.add("alm_verifier_key.py")
    # v0.5 restoration cluster 2 / intent-fidelity module_07: the typed
    # ``MISSING`` sentinel primitive at ``ract.core.sentinels`` lands as
    # a production-ready design tool for new APIs where a caller
    # legitimately needs to pass ``None`` as a distinct explicit value
    # AND a caller-omitted default is meaningfully different from
    # ``None``. Every ``X | None = None`` default in the current tree
    # treats ``None`` as the semantic sentinel already, so forced
    # migration would break callsites without semantic improvement.
    # Adoption is triggered by new-surface need, not by mass-migration
    # of existing callsites (module_07 Flagged gap 9, v0.5 consumer-site
    # design). Allowlist mirrors the transitional-substrate pattern.
    allowlist.add("sentinels.py")
    # v0.5 memory-discipline module_01: the budget accountant helpers at
    # ``ract.memory.{budget_registry,composition,events}`` land under a
    # pre-wired public surface. All three are re-exported from
    # ``ract.memory.__init__`` and consumed by ``tests/memory/``; the
    # shipped-CLI call site lands in memory-discipline module_09 (the
    # SubstrateLoop assembly-to-dispatch wiring). Allowlist mirrors the
    # transitional-substrate pattern used above until module_09 lands
    # the live wiring. (``budget.py`` is imported by all three helpers,
    # so it is not dead.)
    allowlist.add("budget_registry.py")
    allowlist.add("composition.py")
    allowlist.add("events.py")
    # v0.5 memory-discipline module_02: the symbol-index helpers at
    # ``ract.memory.{walker,watcher}`` and the per-language parser
    # dispatchers at ``ract.memory.languages.{python,typescript,rust,go}``
    # are consumed by ``ract.memory.symbol_index`` + ``ract.memory.parser``
    # and by ``tests/memory/``; the shipped-CLI call site lands in
    # memory-discipline module_09 (SubstrateLoop index-refresh wiring).
    # Allowlist mirrors the transitional-substrate pattern used above
    # until module_09 lands the live wiring.
    allowlist.add("walker.py")
    allowlist.add("watcher.py")
    for lang in ("python.py", "typescript.py", "rust.py", "go.py"):
        allowlist.add(lang)
    # v0.5 memory-discipline module_03: graph-index helpers at
    # ``ract.memory.{graph_index,graph_populator,lsp,lsp_fallback}``
    # are consumed by ``tests/memory/`` and by memory-discipline
    # module_05 (retrieve primitive) + module_09 (SubstrateLoop
    # wiring) — the shipped-CLI call site lands in module_09.
    # Allowlist mirrors the transitional-substrate pattern above
    # until module_09 lands the live wiring.
    allowlist.add("graph_index.py")
    allowlist.add("graph_populator.py")
    allowlist.add("lsp.py")
    allowlist.add("lsp_fallback.py")
    # v0.5 memory-discipline module_04 (ADR-0034): semantic-index
    # helpers at ``ract.memory.{semantic_index,embedding,chunker,
    # semantic_builder,cpu_fallback}`` are consumed by
    # ``tests/memory/`` and by memory-discipline module_05
    # (retrieve primitive) + module_09 (SubstrateLoop wiring). The
    # shipped-CLI call site (``ract memory rebuild``) lands in
    # module_09. Allowlist mirrors the transitional-substrate
    # pattern above until module_09 lands the live wiring.
    allowlist.add("semantic_index.py")
    allowlist.add("embedding.py")
    allowlist.add("chunker.py")
    allowlist.add("semantic_builder.py")
    allowlist.add("cpu_fallback.py")
    # v0.5 memory-discipline module_05 (ADR-0035): retrieve primitive
    # helpers at ``ract.memory.{retrieve,cache,chunk,query_trace}`` are
    # consumed by ``tests/memory/`` and by memory-discipline module_06
    # (four function contracts) + module_09 (SubstrateLoop wiring).
    # The shipped-CLI call site (``ract memory retrieve``) lands in
    # module_09. Allowlist mirrors the transitional-substrate pattern
    # above until module_09 lands the live wiring.
    allowlist.add("retrieve.py")
    allowlist.add("cache.py")
    allowlist.add("chunk.py")
    allowlist.add("query_trace.py")
    # v0.5 memory-discipline module_06 (ADR-0036): the four function
    # contracts + shared plumbing at ``ract.memory.functions.*`` +
    # ``ract.memory.session`` are consumed by ``tests/memory/`` and by
    # memory-discipline module_07 (playbook composition) + module_09
    # (SubstrateLoop wiring). The shipped-CLI call site lands in
    # module_09. Allowlist mirrors the transitional-substrate pattern
    # above until module_09 lands the live wiring. The prompt-loader
    # + provider adapter + errors + mock provider are also allowlisted
    # here (all consumed by tests today; live wiring in module_09).
    allowlist.add("contracts.py")
    allowlist.add("intake.py")
    allowlist.add("plan.py")
    allowlist.add("edit.py")
    allowlist.add("provider_adapter.py")
    allowlist.add("prompts_loader.py")
    allowlist.add("mock_provider.py")
    allowlist.add("session.py")
    # ``research.py`` is also a memory-discipline module_06 file, but
    # its basename collides with no other tracked module and it is
    # imported by ``ract.memory.functions.__init__``. Allowlist it
    # here for parity with the sibling four verbs.
    allowlist.add("research.py")
    # ``errors.py`` is used by ``ract.memory.functions.__init__`` but
    # basename collides with no other tracked module.
    allowlist.add("errors.py")
    # v0.5 memory-discipline module_07 (ADR-0037): the playbook
    # composition runner at ``ract.memory.composition_runner`` and
    # the loader package at ``ract.memory.playbooks`` are consumed by
    # ``tests/memory/`` + module_09 (SubstrateLoop wiring). The
    # shipped-CLI call site (``ract memory run <playbook>``) lands in
    # module_09. Allowlist mirrors the transitional-substrate pattern
    # above until module_09 lands the live wiring.
    allowlist.add("composition_runner.py")
    items = DeadCodeAuction(
        project_root,
        config={"min_age_days": 0, "allowlist": allowlist},
    ).scan()
    assert items == [], f"dead-code auction found: {[i.relative_path for i in items]}"


def test_auction_discriminates_dead_from_live_in_src_layout(tmp_path: Path):
    """Two-sided gate: auction flags only the unreferenced module."""
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")

    live = src / "live.py"
    live.write_text("def helper():\n    pass\n", encoding="utf-8")
    _set_old_mtime(live)

    dead = src / "dead.py"
    dead.write_text("def unused():\n    pass\n", encoding="utf-8")
    _set_old_mtime(dead)

    user = src / "main.py"
    user.write_text(
        "from pkg.live import helper\ndef run():\n    helper()\n",
        encoding="utf-8",
    )
    _set_old_mtime(user, days=10)

    items = DeadCodeAuction(
        tmp_path,
        config={"min_age_days": 0, "allowlist": {"main.py"}},
    ).scan()
    paths = [item.relative_path.replace("\\", "/") for item in items]
    assert "src/pkg/dead.py" in paths, paths
    assert "src/pkg/live.py" not in paths, paths
    assert "src/pkg/main.py" not in paths, paths


# RACT 0.1.1 - Trust and tooling
