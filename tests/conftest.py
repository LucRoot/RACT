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
import tempfile

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Give the whole run its own user state directory.

    The state directory holds the repository trust store and the egress
    ledger (B-044). A test run must neither read the operator's trust
    decisions nor write its requests into the operator's ledger, and CLI
    subprocesses inherit the environment, so it is set once for the run.
    """
    state = tempfile.mkdtemp(prefix="ract-test-state-")
    os.environ["LOCALAPPDATA"] = state
    os.environ["XDG_STATE_HOME"] = state


@pytest.fixture(autouse=True)
def _forget_known_values() -> object:
    """V7-05: a key one test's provider registered is not masked in the next test."""
    yield
    from ract import redaction

    redaction.clear_known()
def _forget_ledger_run() -> object:
    """V7-08: a turn run in the test's own thread does not attribute the next test's requests."""
    yield
    from ract import egress_ledger

    egress_ledger.set_run("")


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


@pytest.fixture
def fake_model_server() -> object:
    """Factory for the scripted fake model server (``tests/fixtures``).

    ``server = fake_model_server("j3_ask_code")`` starts a server on an
    ephemeral 127.0.0.1 port and returns it; ``server.base_url`` ends in
    ``/v1`` and ``server.requests`` holds what the client sent. Every server
    the test starts is stopped at teardown.
    """
    from tests.fixtures.fake_model_server import FakeModelServer  # noqa: PLC0415

    started: list[FakeModelServer] = []

    def _start(scenario: object) -> FakeModelServer:
        server = FakeModelServer(scenario).start()  # type: ignore[arg-type]
        started.append(server)
        return server

    try:
        yield _start
    finally:
        for server in started:
            server.stop()


# RACT 0.5.2 (CI-fix)
