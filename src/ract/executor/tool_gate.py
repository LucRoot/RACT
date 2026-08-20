"""Tool-invocation gate for SubstrateLoop (SUBSTRATE §5).

DeepSeek REVIEW_2 criticism 3 + REVIEW_3 arch-drift section: the
SubstrateLoop currently DECLARES an OS-enforced capability layer but
delegates tool invocation to whatever caller convention the executor
happens to use, so a tool call that bypasses the check surface never
generates a refusal event and never appears in the invocation audit.

This module lands the single choke point:

- Every tool call goes through ``SubstrateLoop.invoke_tool(tool_id,
  args)`` (wired in ``ract.executor.loop``).
- The gate performs four checks IN ORDER, halting on the first failure:
  1. **Manifest declaration.** ``tool_id`` MUST be in the run's
     ``CapabilityManifest.tools`` allowlist.
  2. **Args conformance.** ``args`` MUST pass the tool's registered
     schema (arg names on an allowlist; scalar types match). Anything
     unknown or wrong-shape refuses.
  3. **Side-effect budget.** Every invocation consumes one unit from
     the per-step ``ToolBudget`` (default: 64 invocations). Overrun
     refuses.
  4. **Pre-execution log.** A ``tool.invocation.pre`` event is
     emitted BEFORE the tool runs (so a crash inside the tool still
     leaves the pre-event on record).
- After the tool returns (or raises), a ``tool.invocation.post`` event
  is emitted with outcome + latency + (bounded) result-size.
- Refusals raise ``ToolInvocationRefused`` (structured; carries the
  gate name that failed, the tool_id, and a human-readable reason).
  The loop controller catches this and either retries within budget
  or halts with a T-cause.

The tool registry is deliberately narrow: a tool is identified by its
``tool_id`` (a stable string), a callable to invoke, and a
``ToolArgSchema`` describing arg-name + type rules. Adding a tool is a
one-line registration; the schema keeps the gate machine-checkable.

Design intent (per REVIEW_2 c.3): pull the enforcement OUT of every
call site and INTO one gate, so a new tool cannot ship without going
through the gate; and so the event log surface for tool invocations is
uniform across the substrate.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ToolInvocationRefused(RuntimeError):
    """Raised when the tool-invocation gate refuses a call.

    Carries structured fields so the caller (loop controller) can
    dispatch on the failure reason without string-parsing:

    - ``tool_id``: the invocation the gate refused.
    - ``gate``: which gate fired (``"manifest"``, ``"args"``,
      ``"budget"``, ``"registry"``).
    - ``reason``: human-readable explanation.
    - ``details``: dict of gate-specific evidence (e.g. the offending
      arg names, the current budget count).
    """

    def __init__(
        self,
        *,
        tool_id: str,
        gate: str,
        reason: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(f"[{gate}] tool {tool_id!r} refused: {reason}")
        self.tool_id = tool_id
        self.gate = gate
        self.reason = reason
        self.details: dict[str, Any] = dict(details) if details else {}


# ---------------------------------------------------------------------------
# Schema / registry
# ---------------------------------------------------------------------------


# Accepted arg types. Keeping the set closed prevents a tool from
# claiming an unbounded type surface. ``None`` is expressible as a
# nullable field via ``optional=True``.
_ALLOWED_TYPES: frozenset[type] = frozenset(
    {str, int, float, bool, list, tuple, dict}
)


@dataclass(frozen=True)
class ToolArgSpec:
    """One argument specification for a tool.

    ``name`` is the arg name (kwargs only -- positional args are not
    supported by the gate). ``type_`` is one of ``_ALLOWED_TYPES``.
    ``optional`` allows the arg to be absent from ``args``.
    """

    name: str
    type_: type
    optional: bool = False

    def __post_init__(self) -> None:
        if self.type_ not in _ALLOWED_TYPES:
            raise ValueError(
                f"ToolArgSpec {self.name!r}: type {self.type_!r} is not in "
                f"the allowed set ({sorted(t.__name__ for t in _ALLOWED_TYPES)})"
            )


@dataclass(frozen=True)
class ToolArgSchema:
    """Argument schema for one tool.

    A schema is a tuple of ``ToolArgSpec``. Args on the schema are the
    ONLY args accepted; any extra key in ``args`` refuses at the
    ``args`` gate.
    """

    args: tuple[ToolArgSpec, ...] = ()

    def validate(self, args: Mapping[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        """Return ``(ok, reason, details)``.

        On success ``reason`` is empty and ``details`` is empty.
        """
        by_name = {spec.name: spec for spec in self.args}
        # Extra keys -- forbidden.
        extras = sorted(set(args.keys()) - set(by_name.keys()))
        if extras:
            return (
                False,
                f"unknown args: {extras}",
                {"unknown_args": extras},
            )
        # Required-arg presence + type conformance.
        for spec in self.args:
            if spec.name not in args:
                if spec.optional:
                    continue
                return (
                    False,
                    f"missing required arg {spec.name!r}",
                    {"missing_arg": spec.name},
                )
            value = args[spec.name]
            # bool is a subclass of int in Python; separate the check
            # so a bool doesn't sneak past an int-only spec.
            if spec.type_ is int and isinstance(value, bool):
                return (
                    False,
                    f"arg {spec.name!r} expected int; got bool",
                    {"arg": spec.name, "value_type": "bool"},
                )
            if not isinstance(value, spec.type_):
                return (
                    False,
                    (
                        f"arg {spec.name!r} type mismatch: expected "
                        f"{spec.type_.__name__}, got {type(value).__name__}"
                    ),
                    {"arg": spec.name, "expected": spec.type_.__name__},
                )
        return (True, "", {})


ToolCallable = Callable[..., Any]


@dataclass(frozen=True)
class ToolDefinition:
    """A registered tool: identifier + schema + callable.

    ``tool_id`` is the string the manifest allowlists.
    ``schema`` is the arg-shape gate. ``call`` is invoked with the
    validated args (as kwargs).
    """

    tool_id: str
    schema: ToolArgSchema
    call: ToolCallable


class ToolRegistry:
    """Per-run, immutable-after-freeze registry of tool definitions.

    A tool cannot be replaced once ``freeze()`` is called. This keeps
    the gate honest -- a compromised call site cannot silently swap a
    tool implementation mid-run to bypass the schema.
    """

    def __init__(self) -> None:
        self._defs: dict[str, ToolDefinition] = {}
        self._frozen = False

    def register(self, defn: ToolDefinition) -> None:
        if self._frozen:
            raise RuntimeError(
                "ToolRegistry is frozen; cannot register more tools mid-run"
            )
        if defn.tool_id in self._defs:
            raise ValueError(
                f"tool {defn.tool_id!r} already registered; use a unique tool_id"
            )
        self._defs[defn.tool_id] = defn

    def freeze(self) -> None:
        self._frozen = True

    def get(self, tool_id: str) -> ToolDefinition | None:
        return self._defs.get(tool_id)

    def declared_ids(self) -> frozenset[str]:
        return frozenset(self._defs.keys())


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


@dataclass
class ToolBudget:
    """Per-step budget for tool invocations.

    ``max_invocations`` caps how many tool calls one step may make.
    Default 64 matches the manifest's default ``processes.max_procs``
    (loose upper bound for a well-behaved single step).
    """

    max_invocations: int = 64
    used: int = 0

    def consume(self) -> bool:
        """Return True if a slot is available and consume it."""
        if self.used >= self.max_invocations:
            return False
        self.used += 1
        return True

    def remaining(self) -> int:
        return max(0, self.max_invocations - self.used)


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolInvocationRecord:
    """One completed (or refused) invocation record.

    Kept as a value so tests can assert on the sequence of records
    without inspecting the event log.
    """

    tool_id: str
    args_repr: str  # bounded repr for logging (not the raw args)
    ok: bool
    refused_gate: str = ""
    refused_reason: str = ""
    latency_ms: float = 0.0
    result_size_bytes: int = 0


class ToolInvocationGate:
    """The single chokepoint for tool calls in SubstrateLoop.

    Wired by ``SubstrateLoop`` at loop construction; the loop's
    ``invoke_tool`` method delegates to ``ToolInvocationGate.invoke``.

    The gate does not own the registry or the manifest -- it takes
    both by reference so tests can drive the gate with a hand-built
    manifest + registry without spinning up a full loop.
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        declared_tool_ids: frozenset[str],
        budget: ToolBudget | None = None,
        step_id_hex: str = "",
        event_sink: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._registry = registry
        # Snapshot the manifest's declared tool ids at gate construction.
        # This is what the "manifest gate" checks against.
        self._declared_tool_ids = frozenset(declared_tool_ids)
        self._budget = budget or ToolBudget()
        self._step_id_hex = step_id_hex
        self._records: list[ToolInvocationRecord] = []
        # Sink defaults to a lazy import of ract.trace.sink.emit so
        # tests can inject a list-collector without importing trace.
        self._event_sink = event_sink or _default_event_sink

    @property
    def records(self) -> tuple[ToolInvocationRecord, ...]:
        return tuple(self._records)

    @property
    def budget(self) -> ToolBudget:
        return self._budget

    def invoke(self, tool_id: str, args: Mapping[str, Any]) -> Any:
        """Run ``tool_id`` with ``args`` through the four-gate check."""
        args_repr = _bounded_repr(args)

        # Gate 1: manifest-declared.
        if tool_id not in self._declared_tool_ids:
            self._refuse(
                tool_id,
                gate="manifest",
                reason=(
                    f"tool {tool_id!r} is not declared in the run's "
                    "CapabilityManifest.tools allowlist"
                ),
                details={
                    "declared_ids": sorted(self._declared_tool_ids),
                },
                args_repr=args_repr,
            )

        # Gate 2 (implicit): registry has an implementation.
        defn = self._registry.get(tool_id)
        if defn is None:
            self._refuse(
                tool_id,
                gate="registry",
                reason=(
                    f"tool {tool_id!r} is declared in the manifest but no "
                    "implementation is registered in the ToolRegistry"
                ),
                details={},
                args_repr=args_repr,
            )
        assert defn is not None  # for type-checkers -- _refuse always raises

        # Gate 3: args schema.
        ok, reason, details = defn.schema.validate(args)
        if not ok:
            self._refuse(
                tool_id,
                gate="args",
                reason=reason,
                details=details,
                args_repr=args_repr,
            )

        # Gate 4: side-effect budget.
        if not self._budget.consume():
            self._refuse(
                tool_id,
                gate="budget",
                reason=(
                    f"tool budget exhausted (used={self._budget.used} "
                    f"of max={self._budget.max_invocations})"
                ),
                details={
                    "used": self._budget.used,
                    "max": self._budget.max_invocations,
                },
                args_repr=args_repr,
            )

        # Pre-execution event.
        self._emit(
            "tool.invocation.pre",
            {
                "tool_id": tool_id,
                "args_repr": args_repr,
                "budget_used": self._budget.used,
                "budget_max": self._budget.max_invocations,
            },
        )

        # Execute. A crash inside the tool still leaves the pre-event
        # on record; the post-event records ok=False + exception name.
        started = time.monotonic()
        try:
            result = defn.call(**args)
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.monotonic() - started) * 1000.0
            self._emit(
                "tool.invocation.post",
                {
                    "tool_id": tool_id,
                    "ok": False,
                    "exception": type(exc).__name__,
                    "latency_ms": latency_ms,
                },
            )
            self._records.append(
                ToolInvocationRecord(
                    tool_id=tool_id,
                    args_repr=args_repr,
                    ok=False,
                    refused_gate="exception",
                    refused_reason=f"{type(exc).__name__}: {exc}",
                    latency_ms=latency_ms,
                )
            )
            raise

        latency_ms = (time.monotonic() - started) * 1000.0
        result_bytes = _approximate_size_bytes(result)
        self._emit(
            "tool.invocation.post",
            {
                "tool_id": tool_id,
                "ok": True,
                "latency_ms": latency_ms,
                "result_size_bytes": result_bytes,
            },
        )
        self._records.append(
            ToolInvocationRecord(
                tool_id=tool_id,
                args_repr=args_repr,
                ok=True,
                latency_ms=latency_ms,
                result_size_bytes=result_bytes,
            )
        )
        return result

    # -----------------------------------------------------------------
    # helpers
    # -----------------------------------------------------------------

    def _refuse(
        self,
        tool_id: str,
        *,
        gate: str,
        reason: str,
        details: Mapping[str, Any],
        args_repr: str,
    ) -> None:
        """Record + emit + raise a structured refusal."""
        self._emit(
            "tool.invocation.refused",
            {
                "tool_id": tool_id,
                "gate": gate,
                "reason": reason,
                "details": dict(details),
            },
        )
        self._records.append(
            ToolInvocationRecord(
                tool_id=tool_id,
                args_repr=args_repr,
                ok=False,
                refused_gate=gate,
                refused_reason=reason,
            )
        )
        raise ToolInvocationRefused(
            tool_id=tool_id, gate=gate, reason=reason, details=details
        )

    def _emit(self, kind: str, payload: dict[str, Any]) -> None:
        # Stamp step_id_hex on every event so downstream joins work
        # even without a live substrate loop.
        payload.setdefault("step_id_hex", self._step_id_hex)
        try:
            self._event_sink(kind, payload)
        except Exception:  # noqa: BLE001 -- never fail a step on a sink error
            _LOG.warning(
                "tool_gate: event sink raised on %r; suppressing", kind
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_MAX_ARGS_REPR = 512


def _bounded_repr(args: Mapping[str, Any]) -> str:
    """Return a size-bounded ``repr`` of ``args`` for logging.

    We never write full arg values into the event log -- a tool that
    reads a secret and passes the value to another tool would leak
    through the audit surface otherwise. The repr is bounded to
    ``_MAX_ARGS_REPR`` chars and ellipsised past that.
    """
    raw = repr(dict(args))
    if len(raw) <= _MAX_ARGS_REPR:
        return raw
    return raw[: _MAX_ARGS_REPR - 3] + "..."


def _approximate_size_bytes(result: Any) -> int:
    """Cheap upper-bound size estimate for the post-event."""
    if result is None:
        return 0
    if isinstance(result, (bytes, bytearray)):
        return len(result)
    try:
        return len(repr(result).encode("utf-8"))
    except Exception:  # noqa: BLE001
        return 0


def _default_event_sink(kind: str, payload: dict[str, Any]) -> None:
    """Forward to ``ract.trace.sink.emit`` when a writer is registered."""
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(kind, payload)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        pass


__all__ = [
    "ToolArgSchema",
    "ToolArgSpec",
    "ToolBudget",
    "ToolDefinition",
    "ToolInvocationGate",
    "ToolInvocationRecord",
    "ToolInvocationRefused",
    "ToolRegistry",
]


# RACT 0.5.1
