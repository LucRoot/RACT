"""Error hierarchy for the four v0.5.0 memory-discipline functions.

Lateral Chain branch D (module_06 PRE): every function raises specific
error types (``EmptyResearchError``, ``BoundedContextError``, ...).
The composition layer wants a single ``try / except`` to route on the
family. This module lands a common base class
:class:`MemoryFunctionError` so callers can catch the family and
dispatch per subclass.

The base subclasses :class:`RuntimeError` (not :class:`Exception`)
because a memory-function failure is a runtime condition tied to a
specific invocation; a caller who lets the error propagate out of
the module is in undefined territory and should crash loudly.
"""

from __future__ import annotations

from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot


class MemoryFunctionError(RuntimeError):
    """Base class for every error raised by the four function contracts.

    Subclasses carry the failing invocation's ``function`` name and an
    optional payload dict for downstream composition. Composition layer
    routes on ``isinstance(err, subtype)`` rather than message parsing.
    """

    function: str

    def __init__(
        self,
        message: str,
        *,
        function: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.function = function
        self.payload: dict[str, Any] = dict(payload or {})
        super().__init__(message)


class EmptyResearchError(MemoryFunctionError):
    """Raised by :func:`~ract.memory.functions.research.research` when the
    retrieve pool returned zero relevant symbols.

    The composition layer decides whether to reindex-and-retry or
    escalate. The payload carries the WorkOrder ``request_type`` and
    the ``mentioned_symbols`` list so the retry heuristic has context.
    """


class OversizedResearchError(MemoryFunctionError):
    """Raised by research when the relevant-symbols pool exceeds the
    hard cap even after one recursive narrowing pass.

    The narrowing cap is 50 relevant symbols (per module_06 spec step
    4). A caller that hits this consistently should refine the
    WorkOrder's ``scope_hints`` before retrying.
    """


class InfeasiblePlanError(MemoryFunctionError):
    """Raised (rather than returned) by plan when the request cannot be
    reduced to a bounded ChangePlan.

    Kept as an explicit error so composition can escalate without
    inspecting a ``status`` field. The payload carries the
    infeasibility reason and any partial :class:`ChangePlan` for
    forensic inspection.
    """


class BoundedContextError(MemoryFunctionError):
    """Raised by :func:`~ract.memory.functions.edit.edit` when the plan's
    ``target_symbols`` themselves exceed the input budget even after
    the load_manifest cascade downgrades wider context.

    Distinct from :class:`ract.memory.retrieve.BoundedContextError`:
    that one fires inside the retrieve primitive; this one fires
    when the plan's targets do not fit under the edit budget after
    the cascade has run. Composition splits the plan or escalates.
    """


class InvalidSyntaxError(MemoryFunctionError):
    """Raised by edit when the provider's response has failed the
    unified-diff validator on every retry.

    ``payload["parse_error"]`` names the first ast-parse failure so
    the composition layer surfaces the concrete parser message to
    the operator rather than "syntax error".
    """


class ProviderContractError(MemoryFunctionError):
    """Raised when a provider response does not match the JSON contract
    the prompt declared.

    Distinct from :class:`InvalidSyntaxError`: this one fires on
    contract violation (missing required field, wrong type, extra
    key) rather than on downstream code parse failure. Retries here
    are the caller's decision; the function raises after the first
    unrecoverable contract violation.
    """


__all__ = [
    "BoundedContextError",
    "EmptyResearchError",
    "InfeasiblePlanError",
    "InvalidSyntaxError",
    "MemoryFunctionError",
    "OversizedResearchError",
    "ProviderContractError",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
