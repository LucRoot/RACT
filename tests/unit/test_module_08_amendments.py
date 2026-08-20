"""Amendment tests for module_08 Second-Pass findings (SP Q1-Q6)."""

from __future__ import annotations

from pathlib import Path


from ract.antilazy.dead_code_polyglot import scan_dead_code
from ract.antilazy.test_copy_paste_polyglot import scan_test_copy_paste
from ract.parsers import tree_sitter_backend as tsb
from ract.parsers.tree_sitter_backend import (
    Language,
    parse,
    reset_grammar_caches,
)


# ---------------------------------------------------------------------------
# SP Q1 -- reset_grammar_caches is public
# ---------------------------------------------------------------------------


def test_sp_q1_reset_grammar_caches_public_symbol() -> None:
    """The public reset makes long-running processes recoverable after a
    mid-session grammar install."""
    reset_grammar_caches()
    # Simulate a failed load.
    tsb._GRAMMAR_UNAVAILABLE.add(Language.PYTHON)
    assert parse("m.py", b"x=1\n") is None
    # The public reset clears the block.
    reset_grammar_caches()
    tree = parse("m.py", b"x=1\n")
    assert tree is not None


def test_sp_q1_reset_grammar_caches_reexported_from_parsers() -> None:
    from ract.parsers import reset_grammar_caches as re_export

    assert re_export is reset_grammar_caches


# ---------------------------------------------------------------------------
# SP Q2 -- Python annotated assignments contribute both a decl and a ref
# ---------------------------------------------------------------------------


def test_sp_q2_ann_assign_target_recorded_as_decl(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text(
        "value: int = 1\n"
        "orphan: int = 2\n"
        "print(value)\n"
    )
    report = scan_dead_code([p])
    idents = {c.identifier for c in report.candidates}
    assert "orphan" in idents
    assert "value" not in idents


def test_sp_q2_ann_assign_annotation_counts_as_ref(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text(
        "class Config:\n    pass\n"
        "cfg: Config = None  # type: ignore\n"
        "print(cfg)\n"
    )
    report = scan_dead_code([p])
    idents = {c.identifier for c in report.candidates}
    # Config is referenced ONLY in the annotation; it must not be
    # flagged dead.
    assert "Config" not in idents


# ---------------------------------------------------------------------------
# SP Q3 -- JS destructuring binding recorded as decl + not spuriously
#          suppressing identically-named decls elsewhere
# ---------------------------------------------------------------------------


def test_sp_q3_js_destructured_binding_walked_by_extractor(tmp_path: Path) -> None:
    """The extractor must NOT silently skip destructured pattern names.

    Verifies at the walker level by using ``_extract_file`` directly:
    the destructured identifier ``distinctivename`` MUST land in the
    declarations list. (Whether it ends up in the final `candidates`
    depends on the reference pass; SP Q3 is specifically about the
    walker's blind spot on the DECL side.)
    """
    from ract.antilazy.dead_code_polyglot import _extract_file

    p = tmp_path / "m.js"
    src = b"const obj = { foo: 1 };\nconst { distinctivename } = obj;\n"
    p.write_bytes(src)
    _lang, decls, _refs = _extract_file(p, src)
    names = {name for name, _kind, _r, _c in decls}
    assert "distinctivename" in names, decls


def test_sp_q3_js_destructured_binding_included_in_refs_pass(
    tmp_path: Path,
) -> None:
    """The destructured NAME position is registered as a decl-id byte
    range so the same position does not double-count as a reference."""
    from ract.antilazy.dead_code_polyglot import _extract_file

    p = tmp_path / "m.js"
    src = b"const obj = { foo: 1 };\nconst { onlyhere } = obj;\n"
    p.write_bytes(src)
    _lang, decls, refs = _extract_file(p, src)
    # `onlyhere` was declared; the reference pass sees the same
    # shorthand_property_identifier_pattern node but skips it because
    # its bytes match the decl entry.
    assert "onlyhere" not in refs
    assert any(name == "onlyhere" for name, *_ in decls)


# ---------------------------------------------------------------------------
# SP Q4 -- Rust prev_attr_text does not leak past a nested mod
# ---------------------------------------------------------------------------


def test_sp_q4_rust_cfg_test_mod_does_not_leak_to_next_sibling(tmp_path: Path) -> None:
    """The attribute on `mod tests` must NOT tag the following free function."""
    p = tmp_path / "lib.rs"
    p.write_text(
        "#[cfg(test)]\n"
        "mod tests {\n"
        "    #[test]\n"
        "    fn inner() {\n"
        "        let x = compute(1);\n"
        "        assert_eq!(x, 2);\n"
        "        assert!(x > 0);\n"
        "    }\n"
        "}\n"
        "fn not_a_test() {\n"
        "    let y = compute(2);\n"
        "    assert_eq!(y, 3);\n"
        "    assert!(y > 0);\n"
        "}\n"
    )
    report = scan_test_copy_paste([p])
    # `not_a_test` must NOT have been extracted as a test body (no
    # `#[test]` attribute in scope), so there is at most ONE test body
    # (`inner`) and therefore NO pair to compare.
    for finding in report.findings:
        assert finding.b_name != "not_a_test"
        assert finding.a_name != "not_a_test"


# ---------------------------------------------------------------------------
# SP Q5 -- iter_nodes stack cap does not corrupt normal walks
# ---------------------------------------------------------------------------


def test_sp_q5_iter_nodes_cap_does_not_affect_normal_input() -> None:
    """A modest tree walks correctly under the default cap of 10k."""
    src = b"def a():\n    return 1\n" * 100
    tree = parse("m.py", src)
    assert tree is not None
    node_types_seen = {getattr(n, "type", "") for n in tsb.iter_nodes(tree.root_node)}
    assert "function_definition" in node_types_seen


def test_sp_q5_iter_nodes_respects_max_depth_none_opt_out() -> None:
    src = b"def a():\n    return 1\n"
    tree = parse("m.py", src)
    assert tree is not None
    # Explicit disable of the cap -- must still complete.
    seen = list(tsb.iter_nodes(tree.root_node, max_stack_depth=None))
    assert seen  # non-empty


# ---------------------------------------------------------------------------
# SP Q6 -- TSX and TS share a copy-paste comparison group
# ---------------------------------------------------------------------------


def test_sp_q6_tsx_and_ts_share_comparison_group(tmp_path: Path) -> None:
    ts = tmp_path / "utils.test.ts"
    tsx = tmp_path / "utils.test.tsx"
    body = (
        "test('adds', () => {\n"
        "  const r = compute(1);\n"
        "  expect(r).toBe(2);\n"
        "  expect(r > 0).toBe(true);\n"
        "});\n"
    )
    ts.write_text(body)
    # A structurally identical body in a .tsx file must pair with the
    # .ts body under the folded typescript/tsx comparison group.
    tsx.write_text(body.replace("adds", "adds_copy"))
    report = scan_test_copy_paste([ts, tsx])
    assert any(
        {f.a_file, f.b_file} == {str(ts), str(tsx)} for f in report.findings
    ), report.findings
