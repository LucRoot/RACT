# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the codebase historian."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import subprocess
from pathlib import Path

from rootact.codebase_historian import CodebaseHistorian


def test_build_indexes_symbols(tmp_path):
    (tmp_path / "mod.py").write_text(
        "def helper(): pass\nclass Thing: pass\n", encoding="utf-8"
    )
    historian = CodebaseHistorian(tmp_path).build()
    assert "mod.helper" in historian.symbol_graph.nodes
    assert historian.symbol_graph.nodes["mod.helper"].symbol_type == "function"


def test_query_ranks_by_keyword_overlap(tmp_path):
    (tmp_path / "payment.py").write_text(
        "def process_payment(): pass\n", encoding="utf-8"
    )
    (tmp_path / "cart.py").write_text("def add_to_cart(): pass\n", encoding="utf-8")
    historian = CodebaseHistorian(tmp_path).build()
    matches = historian.query("payment processing", k=5)
    assert matches
    assert matches[0].name == "process_payment"
    assert all(m.symbol_type != "module" for m in matches)


def test_query_excludes_zero_overlap(tmp_path):
    (tmp_path / "alpha.py").write_text("def alpha(): pass\n", encoding="utf-8")
    historian = CodebaseHistorian(tmp_path).build()
    matches = historian.query("zzzz", k=5)
    assert matches == []


def test_save_and_load_roundtrip(tmp_path):
    (tmp_path / "mod.py").write_text("def helper(): pass\n", encoding="utf-8")
    original = CodebaseHistorian(tmp_path).build()
    save_path = tmp_path / "historian.json"
    original.save(save_path)

    loaded = CodebaseHistorian.load(tmp_path, save_path)
    assert "mod.helper" in loaded.symbol_graph.nodes
    assert loaded.symbol_graph.nodes["mod.helper"].symbol_type == "function"


def test_load_preserves_commit_context(tmp_path):
    (tmp_path / "mod.py").write_text("def helper(): pass\n", encoding="utf-8")
    historian = CodebaseHistorian(tmp_path).build()
    historian.commit_context["mod.helper"] = {
        "commit_hash": "abc123",
        "message": "init",
    }
    save_path = tmp_path / "historian.json"
    historian.save(save_path)

    loaded = CodebaseHistorian.load(tmp_path, save_path)
    assert loaded.commit_context["mod.helper"]["commit_hash"] == "abc123"


def test_build_without_git_does_not_crash(tmp_path):
    (tmp_path / "mod.py").write_text("def helper(): pass\n", encoding="utf-8")
    historian = CodebaseHistorian(tmp_path).build()
    assert historian.commit_context == {}
    assert "mod.helper" in historian.symbol_graph.nodes


def test_query_includes_commit_context(tmp_path):
    (tmp_path / "mod.py").write_text("def helper(): pass\n", encoding="utf-8")
    historian = CodebaseHistorian(tmp_path).build()
    historian.commit_context["mod.helper"] = {
        "commit_hash": "abc123",
        "message": "initial helper",
        "date": "2026-07-01",
    }
    matches = historian.query("helper", k=5)
    helper_match = next(m for m in matches if m.name == "helper")
    assert helper_match.commit_hash == "abc123"
    assert "initial" in (helper_match.commit_message or "")


def test_module_symbols_excluded_from_query(tmp_path):
    (tmp_path / "mod.py").write_text("def helper(): pass\n", encoding="utf-8")
    historian = CodebaseHistorian(tmp_path).build()
    matches = historian.query("mod", k=5)
    assert all(m.symbol_type != "module" for m in matches)


def test_query_excludes_negative_similarity(tmp_path):
    (tmp_path / "mod.py").write_text("def helper(): pass\n", encoding="utf-8")
    historian = CodebaseHistorian(tmp_path).build()
    # "helper" vs "xyz" has zero overlap; the <= 0.0 guard should drop it.
    matches = historian.query("xyz", k=5)
    assert matches == []


def test_module_to_path() -> None:
    from rootact.codebase_historian import _module_to_path

    assert _module_to_path("a.b.c") == Path("a/b/c.py")


def test_blame_line_parses_porcelain_output(tmp_path, monkeypatch):
    (tmp_path / "mod.py").write_text("def helper(): pass\n", encoding="utf-8")
    historian = CodebaseHistorian(tmp_path)
    historian.symbol_graph.build()

    def fake_blame(*args, **kwargs):
        class Result:
            returncode = 0
            stdout = (
                "abc123 1 1 7\n"
                "author Dr. Lucas Root\n"
                "author-time 1719993600\n"
                "summary init helper\n"
            )
            stderr = ""

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_blame)
    context = historian._blame_line(tmp_path / "mod.py", 1)
    assert context is not None
    assert context["commit_hash"] == "abc123"
    assert "init helper" in context["message"]


def test_blame_line_failure_returns_none(tmp_path, monkeypatch):
    (tmp_path / "mod.py").write_text("def helper(): pass\n", encoding="utf-8")
    historian = CodebaseHistorian(tmp_path)

    def fake_blame(*args, **kwargs):
        class Result:
            returncode = 1
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_blame)
    assert historian._blame_line(tmp_path / "mod.py", 1) is None


def test_blame_line_git_not_found_returns_none(tmp_path, monkeypatch):
    (tmp_path / "mod.py").write_text("def helper(): pass\n", encoding="utf-8")
    historian = CodebaseHistorian(tmp_path)

    def fake_blame(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", fake_blame)
    assert historian._blame_line(tmp_path / "mod.py", 1) is None


def test_load_commit_context_attaches_blame(tmp_path, monkeypatch):
    (tmp_path / "mod.py").write_text("def helper(): pass\n", encoding="utf-8")
    historian = CodebaseHistorian(tmp_path)

    monkeypatch.setattr(historian, "_has_git", lambda: True)
    monkeypatch.setattr(
        historian,
        "_blame_line",
        lambda path, line: {
            "commit_hash": "def456",
            "author": "Dr. Root",
            "date": "1719993600",
            "message": "add helper",
        },
    )

    historian.build()
    assert historian.commit_context["mod.helper"]["commit_hash"] == "def456"


# RACT 0.1.0 - Initial Public Release
