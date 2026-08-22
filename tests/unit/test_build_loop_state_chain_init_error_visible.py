"""Regression: :func:`ract.core.loop.build_loop_state` must NOT
silently swallow every exception when appending the initial
:class:`SuiteChain` entry.

v0.5.1 wiring module_06 (Lens G G-06) closure. The prior code was::

    try:
        chain = SuiteChain(run_path)
        if not chain.entries():
            ...
            chain.append(...)
    except Exception:  # noqa: BLE001
        pass

which meant a :class:`SuiteChainCorruptError` at build time entered
the loop silently -- combined with Lens G G-03, a poisoned run_dir
could enter the loop with NO audit trail AND NO rollback target.

The fix narrows the exception surface:

- :class:`SuiteChainCorruptError` is RE-RAISED (data-loss risk).
- :class:`SuiteChainLockContended` is tolerated with an INFO log.
- :class:`OSError` (disk full, perm) is tolerated with a WARN log.

Reference:
- ``_BUILD/audit_2026-08-21/lens_G_loop_controller.md`` G-06.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_06.md``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from ract.core.loop import build_loop_state
from ract.core.predicate import (
    AcceptancePredicate,
    AcceptanceSuite,
    ArtifactInvocation,
    new_intent_id,
    new_predicate_id,
)
from ract.core.suite_chain import SuiteChainCorruptError, SuiteChainLockContended
from ract.core.workspace_digest import compute_prompt_digest
from ract.manager import Plan


def _suite() -> AcceptanceSuite:
    predicate = AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(
            path="__never_present__", must_have_rootknot=False
        ),
        required=True,
    )
    return AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=(predicate,),
        compiled_from="a test intent",
        prompt_digest=bytes(compute_prompt_digest("a test intent")),
    )


def _seed_workspace():
    from ract.core.loop import WorkspaceSnapshot

    return WorkspaceSnapshot(files={"src/foo.py": "print(1)\n"}, timestamp=0.0)


def test_suite_chain_corrupt_error_is_re_raised(tmp_path: Path) -> None:
    """A :class:`SuiteChainCorruptError` at chain-append time MUST
    propagate out of :func:`build_loop_state` -- entering the loop on
    a corrupted chain is a data-loss risk the operator must see.
    """
    suite = _suite()

    def _boom(*args, **kwargs):
        raise SuiteChainCorruptError("simulated corruption at build time")

    with patch("ract.core.suite_chain.SuiteChain.entries", side_effect=_boom):
        with pytest.raises(SuiteChainCorruptError):
            build_loop_state(
                plan=Plan(assumption="a test intent", confidence=1.0, steps=[]),
                workspace=_seed_workspace(),
                suite=suite,
                run_dir=tmp_path,
            )


def test_suite_chain_lock_contended_is_tolerated_and_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Lock contention is TOLERATED (another writer will land the
    entry) but the deferral is logged so operators see it.
    """
    suite = _suite()

    def _contended(*args, **kwargs):
        raise SuiteChainLockContended("simulated contention")

    caplog.set_level(logging.INFO, logger="ract.core.loop")
    with patch("ract.core.suite_chain.SuiteChain.entries", side_effect=_contended):
        state = build_loop_state(
            plan=Plan(assumption="a test intent", confidence=1.0, steps=[]),
            workspace=_seed_workspace(),
            suite=suite,
            run_dir=tmp_path,
        )
    assert state is not None
    assert any(
        "lock contended" in record.message.lower() for record in caplog.records
    ), "lock-contended path must log at INFO"


def test_oserror_at_chain_append_is_tolerated_with_warn(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An :class:`OSError` (disk full, perm) at chain-append time is
    tolerated with a WARN so the loop still proceeds but operators see
    the failure.
    """
    suite = _suite()

    def _oserror(*args, **kwargs):
        raise OSError("simulated disk full")

    caplog.set_level(logging.WARNING, logger="ract.core.loop")
    with patch("ract.core.suite_chain.SuiteChain.entries", side_effect=_oserror):
        state = build_loop_state(
            plan=Plan(assumption="a test intent", confidence=1.0, steps=[]),
            workspace=_seed_workspace(),
            suite=suite,
            run_dir=tmp_path,
        )
    assert state is not None
    warn_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warn_records, "OSError path must log at WARN"
    assert any(
        "OSError" in record.message or "disk full" in record.message
        for record in warn_records
    )


# v0.5.1 module_09 (Lens G G-06 observability closure): LoopState
# now carries ``_last_chain_load_error`` so a swallowed
# chain-init exception is visible to downstream inspection paths
# (``ract inspect state``, tests, operator diagnostics).


def test_chain_init_error_surfaces_on_loop_state(
    tmp_path: Path,
) -> None:
    """A tolerated chain-init exception MUST populate
    ``LoopState._last_chain_load_error``. Fresh construction (no
    exception) leaves the field None.
    """
    suite = _suite()

    # Baseline: fresh construction, chain-init succeeds -> field is None.
    fresh = build_loop_state(
        plan=Plan(assumption="a test intent", confidence=1.0, steps=[]),
        workspace=_seed_workspace(),
        suite=suite,
        run_dir=tmp_path,
    )
    assert fresh._last_chain_load_error is None

    # Tolerated OSError -> field carries the repr.
    def _oserror(*args, **kwargs):
        raise OSError("simulated permission denied")

    tmp_path_2 = tmp_path / "second_run"
    with patch("ract.core.suite_chain.SuiteChain.entries", side_effect=_oserror):
        recovered = build_loop_state(
            plan=Plan(assumption="a test intent", confidence=1.0, steps=[]),
            workspace=_seed_workspace(),
            suite=suite,
            run_dir=tmp_path_2,
        )
    assert recovered._last_chain_load_error is not None
    assert "OSError" in recovered._last_chain_load_error
    assert "permission denied" in recovered._last_chain_load_error

    # Tolerated lock contention -> field carries the repr.
    tmp_path_3 = tmp_path / "third_run"
    with patch(
        "ract.core.suite_chain.SuiteChain.entries",
        side_effect=SuiteChainLockContended("simulated lock contention"),
    ):
        contended = build_loop_state(
            plan=Plan(assumption="a test intent", confidence=1.0, steps=[]),
            workspace=_seed_workspace(),
            suite=suite,
            run_dir=tmp_path_3,
        )
    assert contended._last_chain_load_error is not None
    assert "SuiteChainLockContended" in contended._last_chain_load_error
