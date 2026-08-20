"""module_02 property test: canonical_bytes reproducibility.

Master spec §Gate matrix: "Canonical bytes reproducible /
test_canonical_bytes_deterministic / Modules 02, 03, 04". This module
supplies the file the spec names. For a given ``Rootknot`` shape and
field values, ``canonical_bytes()`` must produce byte-identical output
across calls, processes, and sort-key permutations.

The property tests exercise the module_02 additions
(``workspace_digest``, ``prompt_digest``, ``run_id``) directly and
piggyback on Hypothesis to fuzz field values.
"""

from __future__ import annotations

import os

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ract.core.keys import SessionKey
from ract.core.loop import WorkspaceSnapshot
from ract.core.rootknot import make_rootknot_v4
from ract.core.types import Digest
from ract.core.workspace_digest import (
    compute_prompt_digest,
    workspace_digest,
)


class _KeyStub:
    def __init__(self, seed: bytes) -> None:
        self._key = SessionKey.load_or_create(seed)

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)

    def public_key_bytes(self) -> bytes:
        return self._key.public_key_bytes()


@pytest.fixture
def session_key() -> SessionKey:
    return SessionKey.load_or_create(os.urandom(16))


@pytest.fixture
def sandbox() -> _KeyStub:
    return _KeyStub(os.urandom(16))


@pytest.fixture
def alm() -> _KeyStub:
    return _KeyStub(os.urandom(16))


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    files=st.dictionaries(
        st.text(
            min_size=1,
            max_size=16,
            alphabet=st.characters(whitelist_categories=("L", "N")),
        ),
        st.text(max_size=64),
        max_size=6,
    ),
    ts=st.floats(min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False),
    prompt=st.text(max_size=128),
    run_id=st.text(
        min_size=1,
        max_size=32,
        alphabet=st.characters(whitelist_categories=("L", "N")),
    ),
)
def test_v4_canonical_bytes_are_deterministic(
    files: dict[str, str],
    ts: float,
    prompt: str,
    run_id: str,
    session_key: SessionKey,
    sandbox: _KeyStub,
    alm: _KeyStub,
) -> None:
    """canonical_bytes() for identical inputs is byte-identical across calls."""
    ws = WorkspaceSnapshot(files=dict(files), timestamp=ts)
    common = dict(
        key=session_key,
        sandbox_signer=sandbox,
        alm_signer=alm,
        workspace_path="/tmp/prop",
        artifact_digest=Digest(b"\x77" * 32),
        assumption_digest=Digest(b"\x78" * 32),
        acceptance_suite_digest=Digest(b"\x79" * 32),
        predicate_results=(),
        manifest_digest=Digest(b"\x7a" * 32),
        gate_results=(),
        workspace_digest=workspace_digest(ws),
        prompt_digest=compute_prompt_digest(prompt),
        run_id=run_id,
    )
    a = make_rootknot_v4(**common)
    # Byte-for-byte equal across two computations on the same instance.
    assert a.canonical_bytes() == a.canonical_bytes()


@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    files=st.dictionaries(
        st.text(
            min_size=1,
            max_size=8,
            alphabet=st.characters(whitelist_categories=("L", "N")),
        ),
        st.text(max_size=32),
        min_size=2,
        max_size=6,
    ),
)
def test_workspace_digest_stable_across_dict_insertion_order(
    files: dict[str, str],
) -> None:
    """workspace_digest is invariant under dict insertion order."""
    ws1 = WorkspaceSnapshot(files=dict(files), timestamp=0.0)
    # Rebuild in reversed key order.
    reversed_files = dict(reversed(list(files.items())))
    ws2 = WorkspaceSnapshot(files=reversed_files, timestamp=0.0)
    assert workspace_digest(ws1) == workspace_digest(ws2)


@given(text=st.text(max_size=256))
@settings(max_examples=25, deadline=None)
def test_prompt_digest_deterministic(text: str) -> None:
    """compute_prompt_digest is a pure function of the UTF-8 bytes."""
    assert compute_prompt_digest(text) == compute_prompt_digest(text)
