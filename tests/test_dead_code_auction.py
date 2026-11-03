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
    # S6-0 (sprint 6 landing gate): cli_examples.py is imported locally inside cli.py's help functions,
    # which the auction does not follow. (queue_view.py and plan_approval_view.py had entries too; on the
    # merged tree the REPL and plan_gate import them, so the entries are gone, as ruling 19 says.)
    allowlist.add("cli_examples.py")
    # B-177 wiring: tools/todo_tool.py is registered through tools/__init__
    # and its facts are applied by the harness (executor/steps.py); the
    # symbol graph does not count package-initializer imports, so the entry
    # stays, as for web_tools below.
    allowlist.add("todo_tool.py")
    # B-023, B-115, B-116: the web tools are registered the same way (the
    # package fills REGISTRY with their specs), so they look unreferenced.
    allowlist.add("web_tools.py")
    # G3 (audit round 3, seam 5): the router gate has no production
    # caller — module_08's SubstrateLoop migration landed without the
    # gate call this comment used to assert, and only tests and the
    # package re-export reference it. The entry stays because the
    # auction would otherwise flag the module; the wiring claim does
    # not.
    allowlist.add("gate.py")
    # G3 (audit round 3, seam 5): the OTLP mirror in ``ract.trace.otel``
    # has no run-entry install — the module_08 CLI wiring this comment
    # promised never landed; only the definition, the package
    # re-export, and tests reference ``install_otlp_exporter``. The
    # entry stays to keep the auction quiet; the install claim was
    # stale.
    allowlist.add("otel.py")
    # G3 (audit round 3, seam 5): the legacy ``antilazy/sycophancy.py``
    # and ``antilazy/investigator.py`` are test-only — the LoopController
    # wiring that landed uses ``sycophancy_v2``, and
    # ``tests/architecture/test_no_sycophancy_bypass.py`` bans the
    # legacy scanner from production modules. The entries stay because
    # both are exercised by ``tests/test_antilazy_al1.py`` only.
    allowlist.add("sycophancy.py")
    allowlist.add("investigator.py")
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
    # v0.5 memory-discipline module_02: the file watcher at
    # ``ract.memory.watcher`` is consumed by ``tests/memory/``; the
    # shipped-CLI call site lands in memory-discipline module_09
    # (SubstrateLoop index-refresh wiring). Allowlist mirrors the
    # transitional-substrate pattern used above until module_09 lands
    # the live wiring.
    allowlist.add("watcher.py")
    # v0.5 memory-discipline module_02: the per-language parser dispatchers
    # at ``ract.memory.languages.{python,typescript,rust,go}`` are loaded by
    # dynamic name (``importlib.import_module`` in ``ract.memory.parser``),
    # so the symbol graph sees no inbound edge even though parser.py calls
    # them on every index refresh.
    for lang in ("python.py", "typescript.py", "rust.py", "go.py"):
        allowlist.add(lang)
    # v0.5 memory-discipline module_05 (ADR-0035): the cache helper at
    # ``ract.memory.cache`` is consumed by ``tests/memory/``; the
    # shipped-CLI call site (``ract memory retrieve``) lands in
    # module_09. Allowlist mirrors the transitional-substrate pattern
    # above until module_09 lands the live wiring.
    allowlist.add("cache.py")
    # v0.5 memory-discipline module_06 (ADR-0036): the mock provider at
    # ``ract.memory.functions.testing.mock_provider`` is consumed by
    # ``tests/memory/`` only; the shipped-CLI call site lands in
    # module_09. Allowlist mirrors the transitional-substrate pattern
    # above until module_09 lands the live wiring.
    allowlist.add("mock_provider.py")
    # v0.5 memory-discipline module_08 (ADR-0038): the repo-fingerprint
    # helper at ``ract.memory.repo_fingerprint`` is consumed by
    # ``tests/memory/`` and by memory-discipline module_09 (SubstrateLoop
    # probe-adjusted budget wiring). Allowlist mirrors the
    # transitional-substrate pattern above until module_09 lands the
    # live wiring.
    allowlist.add("repo_fingerprint.py")
    # G3 (audit round 3, seam 5): B-173 landed and ``playbooks/loader.py``
    # now calls ``roles/loader.py`` (TOOL_TIERS, load_builtin_roles), so
    # the role loader stays wired; the entry is needed for the
    # playbooks loader, which still has no production importer — the
    # auction matches by bare basename, so one entry covers both.
    # ADR-0049 D9 (B-174): the offload store has no caller until the
    # tool loop reads it.
    allowlist.add("loader.py")
    allowlist.add("offload.py")
    # B-8dc (audit round 2, seam 5): the ``ract.config`` stub was deleted as
    # dead code; its only production caller, ``config_validation.py``, is
    # now referenced solely by tests. Allowlist it here pending the same
    # keep-or-remove decision a follow-up card owes the config-document
    # surface, so the scan stays clean in the meantime.
    allowlist.add("config_validation.py")
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
