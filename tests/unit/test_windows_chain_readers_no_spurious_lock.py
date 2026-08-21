"""Windows read-path lock regression for chain ledgers.

Lens D D5: ``WorkspaceDigestChain.edges()`` and ``SuiteChain.entries()``
opened their read fd ``O_RDONLY`` and then called
:func:`_lock_exclusive`, which on Windows reduces to
``msvcrt.locking(fd, LK_NBLCK, 1)``. That primitive requires a
WRITE-capable handle, so every non-empty chain read on Windows tripped
``LockContended`` after the three-retry window.

The wiring module_02 fix removes the read-side lock (writers still use
the exclusive lock under ``O_APPEND`` + single-``os.write`` atomicity).
This regression is Windows-only and asserts a 100-iteration read burst
returns edges cleanly.

Reference:
- ``_BUILD/audit_2026-08-21/lens_D_rootknot_signatures.md`` D5.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_02.md``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ract.core.suite_chain import SuiteChain, SuiteChainLockContended
from ract.core.types import Digest
from ract.core.workspace_digest import (
    WorkspaceChainLockContended,
    WorkspaceDigestChain,
)


pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Lens D D5 tripwire is Windows-specific msvcrt.locking behaviour",
)


def _hex_digest(seed: int) -> Digest:
    return Digest(seed.to_bytes(32, "big"))


def test_workspace_chain_edges_100x_no_spurious_lock(tmp_path: Path) -> None:
    """100 sequential ``edges()`` reads on a non-empty chain must not raise."""
    chain = WorkspaceDigestChain(tmp_path)
    # Populate with a small parent tree so ``edges()`` returns non-empty.
    root = _hex_digest(1)
    child = _hex_digest(2)
    grand = _hex_digest(3)
    chain.append(child=root, parent=None)
    chain.append(child=child, parent=root)
    chain.append(child=grand, parent=child)

    for _ in range(100):
        try:
            edges = chain.edges()
        except WorkspaceChainLockContended as exc:  # pragma: no cover -- pre-fix path
            pytest.fail(
                f"WorkspaceChainLockContended raised on Windows read-path (D5): {exc}"
            )
        assert len(edges) == 3


def test_suite_chain_entries_100x_no_spurious_lock(tmp_path: Path) -> None:
    """100 sequential ``entries()`` reads on a non-empty suite chain must not raise."""
    chain = SuiteChain(tmp_path)
    prompt_digest = b"\x11" * 32
    chain.append(
        prompt_digest=prompt_digest,
        suite_digest="a" * 64,
        run_id="rid" + "0" * 29,
        origin="initial",
        rootknot_signature=None,
    )
    chain.append(
        prompt_digest=b"\x22" * 32,
        suite_digest="b" * 64,
        run_id="rid" + "0" * 29,
        origin="operator_recompile",
        rootknot_signature=b"\xcc" * 32,
    )

    for _ in range(100):
        try:
            entries = chain.entries()
        except SuiteChainLockContended as exc:  # pragma: no cover -- pre-fix path
            pytest.fail(
                f"SuiteChainLockContended raised on Windows read-path (D5): {exc}"
            )
        assert len(entries) == 2
