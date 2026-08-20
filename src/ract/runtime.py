"""Ambient run-context accessors for v0.5.1 module_06.

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

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

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


# RACT 0.5.1
