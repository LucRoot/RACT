"""Ambient run-context accessors for v0.5.1 module_06.

SP Q1 note: :class:`contextvars.ContextVar` propagates through
``asyncio.create_task`` and ``asyncio.to_thread`` (Python 3.11+) by
default, but a bare :class:`concurrent.futures.ThreadPoolExecutor`
worker does NOT inherit the parent context. Callers submitting work
into a pool from inside a :func:`bind_run_id` scope must either
(a) use :func:`asyncio.to_thread` / ``loop.run_in_executor``, or
(b) wrap the submitted callable via :func:`run_with_ambient` which
captures the current context and runs the callable under it.



DeepSeek REVIEW_2 criticism 1 ("fragmented ``run_id``") observed that
subsystems each fell back to their own defaults when a caller forgot to
pass ``run_id``: the WAL used its wal_dir basename, the WorkspaceDigestChain
recorded no run_id at all, the event writer took a bytes id at
construction time, and the Rootknot v4 factory required an explicit
kwarg. The result: one loop iteration could emit artifacts stamped with
three or four different identifiers, or (worse) some with the right id
and some with a scratch-directory basename that happened to look like
one.

The structural fix is a single ambient accessor. Every emit-time
subsystem that would otherwise fabricate a default consults
:func:`get_current_run_id` first, and the loop entry binds a single
value for the whole run via :func:`bind_run_id`. Explicit call-site
kwargs still win when supplied (backward-compat with every existing
test that constructs artifacts in isolation) but the ambient fallback
means a NEW subsystem added tomorrow inherits run-id propagation for
free.

Two design choices worth recording:

1. **ContextVar, not thread-local.** RACT's substrate is
   ``asyncio``-clean; a thread-local would drop the id on the first
   ``await``. ``contextvars.ContextVar`` propagates through both
   thread pools and coroutines.

2. **String, not bytes.** The ambient value is the 32-hex string
   shape used by ``Rootknot.run_id``, ``SuiteChain.run_id``, and the
   ``run.completed`` event payload. Callers wanting the 16-byte
   ``Event.run_id`` slot decode via ``bytes.fromhex``; the reverse
   translation is exact and lossless.

Reference:
- ``_BUILD/ract_v0.5.1_external_review_response/module_06.md``.
- ``_BUILD/ract_v0.5.1_external_review/DEEPSEEK_REVIEW_2.md``
  criticism 1.
"""

from __future__ import annotations

import logging
import os
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token, copy_context
from typing import Any, Callable, Iterator, TypeVar

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# ---------------------------------------------------------------------------
# ContextVar
# ---------------------------------------------------------------------------


# ``_CURRENT_RUN_ID`` holds the 32-hex string identifier for the current
# loop run. ``None`` when no loop is active (test fixtures, ad-hoc CLI
# calls, or subsystems constructed for isolation testing). Callers must
# never depend on a specific value here — the accessor is a fallback,
# not a substitute for explicit propagation.
_CURRENT_RUN_ID: ContextVar[str | None] = ContextVar(
    "ract_current_run_id", default=None
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_current_run_id() -> str | None:
    """Return the ambient run_id string, or ``None`` when no loop is active.

    Every RACT subsystem that emits an artifact carrying a ``run_id``
    field (WAL entries, WorkspaceDigestChain edges, SuiteChain entries,
    Rootknot v4 payloads, event log lines) consults this accessor when
    the caller does not pass an explicit kwarg. The value is the same
    32-hex string that
    :func:`ract.core.workspace_digest.run_id_hex` produces.

    Returns ``None`` when the caller has not bound a run_id via
    :func:`bind_run_id` or :func:`set_current_run_id`. Subsystems
    treating this as "no ambient id available" must handle ``None``
    explicitly — the accessor never fabricates a value.
    """
    return _CURRENT_RUN_ID.get()


def set_current_run_id(run_id: str | None) -> Token[str | None]:
    """Set the ambient run_id and return the reset token.

    Prefer :func:`bind_run_id` for scoped use. This lower-level primitive
    is for callers that need finer control over reset timing (e.g., the
    loop controller resetting the id on a non-standard shutdown path).
    """
    if run_id is not None and not isinstance(run_id, str):
        raise TypeError(
            f"run_id must be a str or None; got {type(run_id).__name__}"
        )
    return _CURRENT_RUN_ID.set(run_id)


def reset_current_run_id(token: Token[str | None]) -> None:
    """Reset the ambient run_id using the token returned by
    :func:`set_current_run_id`.
    """
    _CURRENT_RUN_ID.reset(token)


@contextmanager
def bind_run_id(run_id: str) -> Iterator[str]:
    """Context manager: bind ``run_id`` as the ambient value for the block.

    The loop controller uses this at ``run()`` entry so every subsystem
    reached during the loop inherits the id. On exit the previous value
    is restored (typically ``None``), so nested tests that spawn
    sub-runs do not leak ambient state.

    Yields the bound ``run_id`` so callers can write::

        with bind_run_id(rid) as bound:
            do_work(bound)  # same value as rid, but no re-typo path

    Raises ``ValueError`` if ``run_id`` is empty or not a string — an
    empty run_id downstream would silently defeat the propagation.
    """
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(
            f"bind_run_id requires a non-empty string; got {run_id!r}"
        )
    token = _CURRENT_RUN_ID.set(run_id)
    try:
        yield run_id
    finally:
        _CURRENT_RUN_ID.reset(token)


# ---------------------------------------------------------------------------
# SP Q1 amendment -- executor propagation helper
# ---------------------------------------------------------------------------


_R = TypeVar("_R")


def run_with_ambient(
    fn: Callable[..., _R], /, *args: Any, **kwargs: Any
) -> Callable[[], _R]:
    """Return a zero-arg callable that runs ``fn(*args, **kwargs)`` under
    a snapshot of the CALLER's context.

    SP Q1 amendment (external reviewer DEFECT verdict):
    :class:`contextvars.ContextVar` does NOT propagate into
    :class:`concurrent.futures.ThreadPoolExecutor` worker threads by
    default. The snapshot must be captured in the CALLER's context;
    calling :func:`contextvars.copy_context` from inside the worker
    captures the worker's (empty) context instead. This helper
    captures at call time and returns a closure the pool can invoke::

        with bind_run_id(rid):
            with ThreadPoolExecutor() as pool:
                pool.submit(run_with_ambient(subsystem_write, arg1, arg2))

    The returned closure takes no arguments; the pool calls it with
    no args, and it runs the original ``fn(*args, **kwargs)`` under
    the captured context, so the worker sees the ambient run_id the
    caller had bound.

    Kept as a small, dependency-free helper so callers do not need to
    import :mod:`contextvars` at every submit site.
    """
    ctx = copy_context()

    def _bound() -> _R:
        return ctx.run(fn, *args, **kwargs)

    return _bound


# ---------------------------------------------------------------------------
# v0.5.2 module_04 -- subprocess subagent env-boot ambient plumbing
# ---------------------------------------------------------------------------


_LOG = logging.getLogger("ract.runtime")


#: Env var name RACT injects into subprocess subagents to carry the
#: parent's ambient run_id across the process boundary. The value is
#: injected by :meth:`ract.executor.loop.SubstrateLoop.spawn_step_subprocess`
#: AFTER the sandbox env scrub strips any parent-supplied value (see
#: :data:`ract.security.sandbox_env.RACT_INTERNAL_ENV_KEYS`) so an
#: attacker running ``RACT_RUN_ID=victim ract loop ...`` cannot poison
#: a subagent's ambient.
RACT_RUN_ID_ENV_KEY: str = "RACT_RUN_ID"


def bootstrap_ambient_from_env(
    *,
    env: dict[str, str] | None = None,
    emit_events: bool = True,
) -> str:
    """Read ``RACT_RUN_ID`` from env and bind the ambient run_id.

    v0.5.2 module_04 (DA-B F-3.1 closure). Subprocess subagents call
    this once at startup so any ambient-aware subsystem they touch
    (JsonlEventWriter, Rootknot v4 factory, WorkspaceDigestChain,
    WAL) sees the SAME run_id the parent bound.

    Behavior:

    - When ``env`` (default ``os.environ``) carries a non-empty
      ``RACT_RUN_ID``, that value is bound as the ambient and
      returned. A ``runtime.run_id.env_injected`` trace event fires
      when ``emit_events`` is True.
    - When ``RACT_RUN_ID`` is absent OR empty, a synthetic
      ``RUN-ORPHAN-{uuid4}`` is generated + bound + returned. A
      ``runtime.run_id.orphan_generated`` trace event fires when
      ``emit_events`` is True.

    Orphan generation (not fail-closed) is the Ox Alpha co-build
    Fork 2 verdict: subagents legitimately invoked outside a RACT
    parent (operator debugging, external orchestrator) still run +
    write their own audit trail. A ``--strict-orphans`` mode is
    reserved for v0.6.

    Returns the bound run_id (the real value OR the synthetic
    orphan). Never raises.
    """
    source_env = os.environ if env is None else env
    raw = source_env.get(RACT_RUN_ID_ENV_KEY, "")
    if raw:
        set_current_run_id(raw)
        if emit_events:
            _emit_runtime_event(
                "runtime.run_id.env_injected",
                {
                    "run_id": raw,
                    "child_pid": os.getpid(),
                    "source": "env",
                },
            )
        _LOG.info(
            "runtime: bound ambient run_id from RACT_RUN_ID env "
            "(pid=%d, run_id=%s)",
            os.getpid(),
            raw,
        )
        return raw

    synthetic = f"RUN-ORPHAN-{uuid.uuid4().hex}"
    set_current_run_id(synthetic)
    if emit_events:
        _emit_runtime_event(
            "runtime.run_id.orphan_generated",
            {
                "synthetic_run_id": synthetic,
                "reason": "RACT_RUN_ID env var absent or empty",
                "child_pid": os.getpid(),
            },
        )
    _LOG.warning(
        "runtime: RACT_RUN_ID env var absent; generated synthetic "
        "orphan run_id=%s (pid=%d). Subagent is running outside a "
        "RACT-plumbed parent; its trace/sidecar output will carry "
        "the RUN-ORPHAN-* stamp.",
        synthetic,
        os.getpid(),
    )
    return synthetic


def _emit_runtime_event(kind: str, payload: dict[str, Any]) -> None:
    """Best-effort trace event emit. Never raises.

    Follows the module_05 wiring pattern used by
    :func:`ract.executor.loop._emit_process_reaped` -- try the ambient
    sink; log at INFO on absence.
    """
    try:
        from ract.trace.sink import emit as _emit  # noqa: PLC0415

        _emit(kind, payload)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 -- audit signal, not load-bearing
        _LOG.info("runtime trace event %s payload=%s", kind, payload)


# RACT 0.5.2 module_04
