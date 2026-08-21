"""Integration: polyglot G5/G6 fires on .ts / .rs / .go patches.

Contract (v0.5.1 wiring module_07, Lens E AL-E-02 closure):

- ``LoopController._collect_changed_polyglot_files`` returns the
  changed files across polyglot-supported extensions (.py, .ts, .tsx,
  .js, .jsx, .rs, .go, .rb) — filtered against the baseline snapshot.
- ``LoopController._run_polyglot_g5_g6`` invokes
  :func:`ract.antilazy.pre_commit.dispatch_polyglot_g5_g6` on the
  filtered set — a change in a .ts file lands with language
  attribution (not silently skipped).
- The polyglot outcomes each carry a non-empty ``rootknot_signature``
  (AL-1 invariant, module_07 item 4).
"""

from __future__ import annotations

from pathlib import Path


def _make_controller(tmp_path: Path):
    from ract.loop_controller import LoopController

    cfg = tmp_path / "ract.yaml"
    cfg.write_text("providers: {}\n", encoding="utf-8")
    return LoopController(cfg)


def test_dispatch_polyglot_g5_g6_returns_al1_signed_outcomes():
    """Regardless of language mix the outcomes carry AL-1 signatures."""
    from ract.antilazy.pre_commit import dispatch_polyglot_g5_g6

    dead_code, copy_paste = dispatch_polyglot_g5_g6([])
    assert dead_code.rootknot_signature.startswith("sha256:")
    assert copy_paste.rootknot_signature.startswith("sha256:")


def test_collect_changed_polyglot_files_picks_up_ts_rs_go(tmp_path):
    """A .ts + .rs + .go new file each appears in the changed set."""
    controller = _make_controller(tmp_path)
    (tmp_path / "a.ts").write_text("export const x = 1;\n", encoding="utf-8")
    (tmp_path / "b.rs").write_text("fn main() {}\n", encoding="utf-8")
    (tmp_path / "c.go").write_text("package main\n", encoding="utf-8")
    (tmp_path / "keep.md").write_text("# README\n", encoding="utf-8")  # skipped
    changed = controller._collect_changed_polyglot_files(iteration=None)  # type: ignore[arg-type]
    names = sorted(p.name for p in changed)
    assert "a.ts" in names
    assert "b.rs" in names
    assert "c.go" in names
    assert "keep.md" not in names  # .md is not in the polyglot set


def test_collect_changed_polyglot_files_respects_baseline(tmp_path):
    """A file whose contents match the baseline snapshot is NOT changed."""
    controller = _make_controller(tmp_path)
    unchanged = tmp_path / "keep.ts"
    unchanged.write_text("const x = 1;\n", encoding="utf-8")
    # Prime the baseline with the current contents of keep.ts (as if
    # iteration 0 captured it) but leave changed.ts absent from the
    # baseline so it counts as new.
    controller._baseline_snapshot = {"keep.ts": "const x = 1;\n"}
    changed_file = tmp_path / "changed.ts"
    changed_file.write_text("const y = 2;\n", encoding="utf-8")
    changed = controller._collect_changed_polyglot_files(iteration=None)  # type: ignore[arg-type]
    names = sorted(p.name for p in changed)
    assert "changed.ts" in names
    assert "keep.ts" not in names


def test_run_polyglot_g5_g6_returns_empty_when_no_changes(tmp_path):
    controller = _make_controller(tmp_path)
    controller._baseline_snapshot = {}
    assert controller._run_polyglot_g5_g6(iteration=None) == ""  # type: ignore[arg-type]


def test_dispatch_polyglot_g5_g6_language_attribution_on_ts(tmp_path):
    """A .ts file with a dead-code candidate lands with typescript attribution.

    The polyglot backend requires tree-sitter to actually surface a
    finding; when tree-sitter is missing the file lands in
    ``unsupported_languages`` — either way the report has language
    attribution (not silently 'python only').
    """
    from ract.antilazy.pre_commit import dispatch_polyglot_g5_g6

    ts_path = tmp_path / "sample.ts"
    ts_path.write_text(
        "function unused() { return 1; }\nexport const y = 2;\n",
        encoding="utf-8",
    )
    dead_code, _ = dispatch_polyglot_g5_g6([ts_path])
    report = dead_code.report
    # Report either surfaces candidates (tree-sitter present) or
    # names TypeScript in unsupported_languages (fallback). What we
    # assert is that the report is language-aware — it MENTIONS ts.
    unsupported = getattr(report, "unsupported_languages", ())
    candidates = getattr(report, "candidates", ())
    saw_ts = any("typescript" in str(u).lower() for u in unsupported)
    saw_ts = saw_ts or any(
        str(getattr(c, "language", "")).lower() == "typescript" for c in candidates
    )
    assert saw_ts, (
        f"expected TypeScript to appear in report language attribution; "
        f"unsupported={list(unsupported)!r} candidates="
        f"{[getattr(c, 'language', '?') for c in candidates]!r}"
    )
