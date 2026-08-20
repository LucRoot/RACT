"""module_02 tests: WorkspaceDigestChain ancestor semantics.

DEEPSEEK_REVIEW_5 §G2 verification note names the ancestor check as
the load-bearing operation: at compaction #118, before accepting any
artifact from #117, verify that the artifact's workspace_digest is a
parent of the current snapshot chain. Module_02 implements this via
:class:`ract.core.workspace_digest.WorkspaceDigestChain` — an
append-only ledger of ``(child_digest, parent_digest)`` edges at
``.ract/workspace_chain.jsonl``.

Tests:

- Ancestor case: #117 is recorded as parent of #118 → is_ancestor(#117,
  #118) is True.
- Non-ancestor case: two independent roots → is_ancestor between them
  is False.
- Multi-hop: #117 -> #118 -> #119 → is_ancestor(#117, #119) is True.
- Reflexive: is_ancestor(x, x) is False (strict-parent convention).
- Cycle safety: a self-referential edge does not infinite-loop.
- Truncated tail line: warned + tolerated.
- Malformed middle line: raises WorkspaceChainCorruptError.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.core.types import Digest
from ract.core.workspace_digest import (
    WorkspaceChainCorruptError,
    WorkspaceDigestChain,
)


def _d(byte: int) -> Digest:
    """Build a distinctive 32-byte Digest keyed off ``byte``."""
    return Digest(bytes([byte]) * 32)


def test_is_ancestor_true_for_parent_child(tmp_path: Path) -> None:
    """Snapshot #117 recorded as parent of #118 → is_ancestor True."""
    chain = WorkspaceDigestChain(tmp_path)
    d117 = _d(0x71)
    d118 = _d(0x72)
    chain.append(child=d117, parent=None)
    chain.append(child=d118, parent=d117)
    assert chain.is_ancestor(d117, d118) is True


def test_is_ancestor_false_for_non_ancestor(tmp_path: Path) -> None:
    """Two independent roots: neither is ancestor of the other."""
    chain = WorkspaceDigestChain(tmp_path)
    a = _d(0xA0)
    b = _d(0xB0)
    chain.append(child=a, parent=None)
    chain.append(child=b, parent=None)
    assert chain.is_ancestor(a, b) is False
    assert chain.is_ancestor(b, a) is False


def test_is_ancestor_reverses_direction(tmp_path: Path) -> None:
    """Ancestor direction is not commutative."""
    chain = WorkspaceDigestChain(tmp_path)
    root = _d(0x01)
    child = _d(0x02)
    chain.append(child=root, parent=None)
    chain.append(child=child, parent=root)
    assert chain.is_ancestor(root, child) is True
    assert chain.is_ancestor(child, root) is False


def test_is_ancestor_multi_hop(tmp_path: Path) -> None:
    """A deeper chain still resolves ancestry."""
    chain = WorkspaceDigestChain(tmp_path)
    a, b, c, d = _d(0x10), _d(0x20), _d(0x30), _d(0x40)
    chain.append(child=a, parent=None)
    chain.append(child=b, parent=a)
    chain.append(child=c, parent=b)
    chain.append(child=d, parent=c)
    assert chain.is_ancestor(a, d) is True
    assert chain.is_ancestor(b, d) is True
    assert chain.is_ancestor(c, d) is True
    assert chain.is_ancestor(d, a) is False


def test_is_ancestor_reflexive_returns_false(tmp_path: Path) -> None:
    """is_ancestor(x, x) is False (strict-parent convention)."""
    chain = WorkspaceDigestChain(tmp_path)
    a = _d(0x50)
    chain.append(child=a, parent=None)
    assert chain.is_ancestor(a, a) is False


def test_is_ancestor_stops_on_cycle(tmp_path: Path) -> None:
    """A malformed self-referential edge does not infinite-loop."""
    chain = WorkspaceDigestChain(tmp_path)
    a = _d(0x60)
    b = _d(0x61)
    chain.append(child=a, parent=b)
    chain.append(child=b, parent=a)  # cycle
    # Neither answer is a real ancestry; walker bails out via visited.
    assert chain.is_ancestor(_d(0xFE), a) is False


def test_parent_of_returns_correct_parent(tmp_path: Path) -> None:
    """parent_of returns the parent hex digest, or None for a root."""
    chain = WorkspaceDigestChain(tmp_path)
    root = _d(0x70)
    child = _d(0x71)
    chain.append(child=root, parent=None)
    chain.append(child=child, parent=root)
    assert chain.parent_of(root) is None
    assert chain.parent_of(child) == root.hex()


def test_truncated_tail_line_tolerated(tmp_path: Path, caplog) -> None:
    """A truncated last line is skipped with a WARN; earlier edges survive."""
    chain = WorkspaceDigestChain(tmp_path)
    root = _d(0x80)
    child = _d(0x81)
    chain.append(child=root, parent=None)
    chain.append(child=child, parent=root)
    # Truncate the last line of the ledger.
    chain_path = tmp_path / "workspace_chain.jsonl"
    raw = chain_path.read_bytes()
    # Corrupt the last full line by chopping its final 4 bytes; keep
    # the trailing newline off so it looks torn.
    lines = raw.rstrip(b"\n").split(b"\n")
    if lines:
        lines[-1] = lines[-1][:-4]
    chain_path.write_bytes(b"\n".join(lines))
    import logging

    with caplog.at_level(logging.WARNING, logger="ract.core.workspace_digest"):
        edges = chain.edges()
    # First edge survives; second was corrupted at tail.
    assert any(edge.child == root.hex() for edge in edges)
    # WARN emitted for truncated tail.
    assert any("truncated" in rec.message.lower() for rec in caplog.records)


def test_malformed_middle_line_raises(tmp_path: Path) -> None:
    """A malformed middle line raises WorkspaceChainCorruptError."""
    chain = WorkspaceDigestChain(tmp_path)
    a = _d(0x90)
    b = _d(0x91)
    c = _d(0x92)
    chain.append(child=a, parent=None)
    chain.append(child=b, parent=a)
    chain.append(child=c, parent=b)
    # Splice in a broken middle line between the first and second edges.
    chain_path = tmp_path / "workspace_chain.jsonl"
    raw = chain_path.read_bytes()
    lines = raw.rstrip(b"\n").split(b"\n")
    # Insert garbage at position 1 (between the first and second valid line).
    lines.insert(1, b"{ not valid json")
    chain_path.write_bytes(b"\n".join(lines) + b"\n")
    with pytest.raises(WorkspaceChainCorruptError):
        chain.edges()


def test_empty_chain_returns_empty_list(tmp_path: Path) -> None:
    """A ledger with no writes returns an empty list on read."""
    chain = WorkspaceDigestChain(tmp_path)
    assert chain.edges() == []
    assert chain.parent_of(_d(0xAA)) is None
    assert chain.is_ancestor(_d(0xAA), _d(0xBB)) is False
