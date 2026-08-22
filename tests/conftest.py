"""Shared pytest fixtures for the RACT test suite.

v0.5.2 CI-fix follow-up (was v0.6 C-8 in the backlog): the ambient
run_id lives in a :class:`contextvars.ContextVar` (``_CURRENT_RUN_ID``
in :mod:`ract.runtime`) and in the ``RACT_RUN_ID`` env var that
:meth:`SubstrateLoop.spawn_step_subprocess` injects into child
processes. Tests that bind or leak either surface poison the next
test's spawn: ``_inject_ract_run_id_env`` sees the leaked ambient and
re-injects ``RACT_RUN_ID`` into the child env, changing the env shape
the leaked-into test asserts on (three subprocess-spawn tests +
one Windows-stub integration test).

The fixture is autouse so every test starts + ends with a clean
ambient. It resets the ContextVar and strips ``RACT_*`` keys from
``os.environ`` at both bracket edges.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _reset_ambient_run_id_and_env() -> object:
    """Clear the ambient ``RACT_RUN_ID`` ContextVar and env keys.

    Runs before AND after every test. Uses direct set/reset on the
    ContextVar rather than the public :func:`bind_run_id` (which
    refuses ``None``) so the reset path is total, not scoped.
    """
    from ract.runtime import _CURRENT_RUN_ID  # noqa: PLC0415

    # Snapshot + scrub before the test.
    _pre_ract_env = {
        k: v for k, v in os.environ.items() if k.upper().startswith("RACT_")
    }
    for k in list(_pre_ract_env):
        del os.environ[k]
    token = _CURRENT_RUN_ID.set(None)

    try:
        yield
    finally:
        # Reset the ContextVar unconditionally, even if the test bound
        # its own value on top (that inner token is on a stack we do
        # not own; the outer reset returns the var to its
        # pre-fixture state).
        try:
            _CURRENT_RUN_ID.reset(token)
        except (ValueError, LookupError):
            _CURRENT_RUN_ID.set(None)
        # Strip RACT_* keys the test may have injected.
        for k in [k for k in os.environ if k.upper().startswith("RACT_")]:
            del os.environ[k]
        # Restore any pre-existing RACT_* env the operator or shell had set.
        for k, v in _pre_ract_env.items():
            os.environ[k] = v


# RACT 0.5.2 (CI-fix)
