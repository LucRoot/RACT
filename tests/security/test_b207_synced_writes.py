"""B-207 (part 1): the signed grant and the handshake registry are written whole and synced.

``grant.sign`` and the registry's signed mark wrote through a fixed
``NAME.tmp`` (two writers collide) with no fsync before the rename, and the
registry itself was written in place. They go through ``write_atomic`` now,
which syncs before the rename. The operator key here is a throwaway key in a
temporary user folder.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ract.atomic_write import write_atomic
from ract.handshake_registry import HandshakeRegistry
from ract.policy.grant import SIGNATURE_FILE
from tests.test_j4_named_test_runs import _grant


@pytest.fixture
def order(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    seen: list[object] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd: int) -> None:
        seen.append("fsync")
        real_fsync(fd)

    def replace(src: object, dst: object) -> None:
        seen.append(("replace", Path(str(dst)).name))
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    return seen


def _synced_before(order: list[object], name: str) -> bool:
    index = order.index(("replace", name))
    return index > 0 and order[index - 1] == "fsync"


def test_write_atomic_syncs_before_the_rename(tmp_path: Path, order: list[object]) -> None:
    write_atomic(tmp_path / "f.json", b"{}")
    assert _synced_before(order, "f.json")


def test_the_grant_signature_is_synced_and_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, order: list[object]
) -> None:
    cfg = tmp_path / "user-config"
    monkeypatch.setenv("APPDATA", str(cfg))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    root = tmp_path / "project"
    root.mkdir()
    _grant(root)
    assert (root / ".ract" / SIGNATURE_FILE).is_file()
    assert _synced_before(order, SIGNATURE_FILE)
    assert not list((root / ".ract").glob("*.tmp"))


def test_the_handshake_registry_is_replaced_whole_and_synced(
    tmp_path: Path, order: list[object]
) -> None:
    registry = HandshakeRegistry(tmp_path)
    registry.add("m1", "a milestone", "it works")
    assert _synced_before(order, registry.registry_path.name)
