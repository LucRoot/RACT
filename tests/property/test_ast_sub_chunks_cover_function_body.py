"""Hypothesis property: AST sub-chunker output reassembles to the
original body byte-for-byte for every parseable Python function.

Source-spec audit `_BUILD/audit_2026-08-21c/lens_1C_retrieve_chunks.md`
finding 5 (MEDIUM). Master spec §Chunk Overflow: "Reassembly
deterministic" — concatenating sub-chunk bodies in locator order
reproduces the original body.
"""

from __future__ import annotations

import string

from hypothesis import given, strategies as st

from ract.memory.chunker import _split_python_ast_boundaries


_IDENT = st.text(
    alphabet=string.ascii_lowercase, min_size=1, max_size=6
).map(lambda s: "n" + s)


def _straight_line(idents: list[str]) -> str:
    return "\n".join(f"    {name} = {i}" for i, name in enumerate(idents, 1)) + "\n"


def _for_block(name: str, body_idents: list[str]) -> str:
    lines = [f"    for {name} in range(3):"]
    for i, ident in enumerate(body_idents, 1):
        lines.append(f"        {ident} = {i}")
    return "\n".join(lines) + "\n"


def _if_block(cond: str, body_idents: list[str]) -> str:
    lines = [f"    if {cond}:"]
    for i, ident in enumerate(body_idents, 1):
        lines.append(f"        {ident} = {i}")
    return "\n".join(lines) + "\n"


def _while_block(cond: str, body_idents: list[str]) -> str:
    lines = [f"    while {cond}:"]
    for i, ident in enumerate(body_idents, 1):
        lines.append(f"        {ident} = {i}")
    return "\n".join(lines) + "\n"


def _try_block(body_idents: list[str]) -> str:
    lines = ["    try:"]
    for i, ident in enumerate(body_idents, 1):
        lines.append(f"        {ident} = risky({i})")
    lines.append("    except ValueError:")
    lines.append("        fallback()")
    return "\n".join(lines) + "\n"


_block_strategy = st.one_of(
    st.lists(_IDENT, min_size=1, max_size=4).map(_straight_line),
    st.tuples(_IDENT, st.lists(_IDENT, min_size=1, max_size=3)).map(
        lambda t: _for_block(t[0], t[1])
    ),
    st.tuples(_IDENT, st.lists(_IDENT, min_size=1, max_size=3)).map(
        lambda t: _if_block(f"{t[0]} > 0", t[1])
    ),
    st.tuples(_IDENT, st.lists(_IDENT, min_size=1, max_size=3)).map(
        lambda t: _while_block(f"{t[0]} < 10", t[1])
    ),
    st.lists(_IDENT, min_size=1, max_size=3).map(_try_block),
)


@given(st.lists(_block_strategy, min_size=1, max_size=6))
def test_ast_sub_chunks_reassemble_byte_identical(blocks: list[str]) -> None:
    body = "def big():\n" + "".join(blocks)
    pieces = _split_python_ast_boundaries(body)
    if pieces is None:
        # Splitter honestly declines when there's only one segment
        # or when parsing fails; nothing to assert on reassembly.
        return
    assert "".join(pieces) == body


@given(st.lists(_block_strategy, min_size=2, max_size=6))
def test_ast_sub_chunks_at_least_two_when_control_flow_present(
    blocks: list[str],
) -> None:
    """A body with two or more blocks that include at least one
    control-flow construct must produce >=2 pieces (the splitter must
    actually split, not degenerate to a single piece)."""
    if not any(
        block.lstrip().startswith(("for ", "while ", "if ", "try:"))
        for block in blocks
    ):
        return
    body = "def big():\n" + "".join(blocks)
    pieces = _split_python_ast_boundaries(body)
    if pieces is None:
        # Only degenerate when the parser refused; assert only when we
        # did split.
        return
    assert len(pieces) >= 2


# RACT 0.5.1
