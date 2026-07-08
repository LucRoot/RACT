# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the codebase gravity scorer."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.gravity_scorer import GravityScorer


def test_indexes_functions_and_classes(tmp_path):
    (tmp_path / "mod.py").write_text(
        "def helper(): pass\nclass Thing: pass\n", encoding="utf-8"
    )
    scorer = GravityScorer(tmp_path)
    index = scorer.build_index()
    keys = {k.split(".")[-1] for k in index}
    assert "helper" in keys
    assert "Thing" in keys


def test_reference_count_increases_gravity(tmp_path):
    (tmp_path / "core.py").write_text("def util(): pass\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from core import util\nutil()\nutil()\n", encoding="utf-8"
    )
    scorer = GravityScorer(tmp_path)
    index = scorer.build_index()
    util = index["core.util"]
    assert util.reference_count >= 2
    assert util.gravity_score > 0.0


def test_top_k_filters_by_intent(tmp_path):
    (tmp_path / "core.py").write_text(
        "def fetch(): pass\ndef save(): pass\n", encoding="utf-8"
    )
    (tmp_path / "main.py").write_text(
        "from core import fetch\nfetch()\n", encoding="utf-8"
    )
    scorer = GravityScorer(tmp_path)
    top = scorer.top_k(intent="fetch", k=5)
    names = {s.name for s in top}
    assert "fetch" in names


def test_cache_reloads_when_fresh(tmp_path):
    (tmp_path / "mod.py").write_text("def a(): pass\n", encoding="utf-8")
    scorer = GravityScorer(tmp_path)
    scorer.build_index()

    scorer2 = GravityScorer(tmp_path)
    index = scorer2.get_index()
    assert "mod.a" in index


def test_cache_rebuilds_when_file_changes(tmp_path):
    (tmp_path / "mod.py").write_text("def a(): pass\n", encoding="utf-8")
    scorer = GravityScorer(tmp_path)
    scorer.build_index()

    (tmp_path / "mod.py").write_text("def a(): pass\ndef b(): pass\n", encoding="utf-8")
    scorer2 = GravityScorer(tmp_path)
    index = scorer2.get_index()
    assert "mod.b" in index


def test_top_k_returns_limited_results(tmp_path):
    (tmp_path / "mod.py").write_text(
        "def a(): pass\ndef b(): pass\ndef c(): pass\n", encoding="utf-8"
    )
    scorer = GravityScorer(tmp_path)
    top = scorer.top_k(k=2)
    assert len(top) == 2


def test_empty_project_returns_empty_index(tmp_path):
    scorer = GravityScorer(tmp_path)
    index = scorer.build_index()
    assert index == {}


def test_syntax_error_file_is_skipped(tmp_path):
    (tmp_path / "bad.py").write_text("def broken(\n", encoding="utf-8")
    (tmp_path / "good.py").write_text("def ok(): pass\n", encoding="utf-8")
    scorer = GravityScorer(tmp_path)
    index = scorer.build_index()
    assert "good.ok" in index
    assert "bad.broken" not in index


def test_import_statements_are_recorded(tmp_path):
    (tmp_path / "core.py").write_text("def util(): pass\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "import os\nfrom pathlib import Path\nimport core\ncore.util()\n",
        encoding="utf-8",
    )
    scorer = GravityScorer(tmp_path)
    index = scorer.build_index()
    assert "core.util" in index
    # Imports should not crash; core.util reference is still counted.
    assert index["core.util"].reference_count >= 1


def test_attribute_reference_increments_gravity(tmp_path):
    (tmp_path / "core.py").write_text(
        "class Helper:\n    def work(self): pass\n", encoding="utf-8"
    )
    (tmp_path / "main.py").write_text(
        "from core import Helper\nhelper = Helper()\nhelper.work()\n",
        encoding="utf-8",
    )
    scorer = GravityScorer(tmp_path)
    index = scorer.build_index()
    assert "core.Helper" in index
    assert index["core.Helper"].reference_count >= 1


def test_corrupt_cache_triggers_rebuild(tmp_path):
    (tmp_path / "mod.py").write_text("def a(): pass\n", encoding="utf-8")
    cache_dir = tmp_path / ".rootact"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "gravity_index.json").write_text("not json", encoding="utf-8")
    scorer = GravityScorer(tmp_path)
    index = scorer.get_index()
    assert "mod.a" in index


def test_loads_fresh_cache_without_rescan(tmp_path):
    (tmp_path / "mod.py").write_text("def a(): pass\n", encoding="utf-8")
    scorer = GravityScorer(tmp_path)
    scorer.build_index()

    # Simulate a new scorer that finds the cache fresh and loads it.
    scorer2 = GravityScorer(tmp_path)
    scorer2.get_index()
    # _symbols should be populated from cache, not a fresh build.
    assert "mod.a" in scorer2._symbols
