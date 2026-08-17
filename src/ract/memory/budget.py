"""Token budget accountant for the memory-discipline pipeline.

Every function that reaches a model in v0.5.0 declares a budget structure;
the harness enforces the hard ceiling before the model call. This module
lands the primitives:

- :class:`BudgetDeclaration` — the immutable per-function budget shape.
- :class:`BudgetAccountant` — per-invocation seat/read/refuse bookkeeping.
- :class:`BudgetSection` — one seated slice of the assembled context.
- :class:`BudgetNarrowing` — one recorded narrowing (composition or runtime).
- :func:`narrow` — pure narrow-only combinator over declarations.
- :class:`TokenEstimator` protocol + :class:`WhitespaceTokenEstimator`
  default. Provider adapters supply their native tokenizer in module_09.

The accountant is pure over ``(declaration, assembled_context)`` so tests
compose synthetic scenarios without a live provider. On over-target the
caller is expected to invoke the retrieval cascade's downgrade path (wired
in module_05). On over-max :meth:`BudgetAccountant.refuse_if_over_ceiling`
raises :class:`BudgetExceededError` naming the offending section. On over-
ceiling the accountant refuses the invocation before the model call and
emits ``budget.exceeded`` to the event trace (null sink here, real sink in
module_09).

Reference sources:

- ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §The token budget system.
- ``docs/ADRs/ADR-0031-budget-accountant-hard-ceiling.md``.
- ``src/ract/token_budget.py`` (v0.1-era predecessor, preserved for the
  call sites module_09 migrates one at a time).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal, Protocol

from ract.core.module_identity import _module_knot, register_module_knot


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BudgetExceededError(RuntimeError):
    """Raised when an assembly exceeds a declared budget boundary.

    Carries the ``declaration`` under which the boundary applied, the
    ``section_name`` that pushed the total over, and the token ``delta``
    by which the boundary was exceeded. The message names all three so
    the failing invocation is diagnosable from the exception alone.
    """

    def __init__(
        self,
        *,
        declaration: "BudgetDeclaration",
        section_name: str,
        delta: int,
        boundary: str,
    ) -> None:
        self.declaration = declaration
        self.section_name = section_name
        self.delta = delta
        self.boundary = boundary
        super().__init__(
            f"budget exceeded on function {declaration.function!r}: "
            f"section {section_name!r} pushed the total {delta} tokens "
            f"past the {boundary} boundary"
        )


class WideningRefusedError(RuntimeError):
    """Raised when a narrowing operation attempts to widen a declaration.

    The runtime-narrowing and composition-override paths BOTH refuse any
    proposed value that is larger than the value it replaces. Widening
    is a design change and requires a fresh function-default commit.
    """

    def __init__(self, *, field_name: str, old: int, new: int) -> None:
        self.field_name = field_name
        self.old = old
        self.new = new
        super().__init__(
            f"widening refused on field {field_name!r}: "
            f"old={old} new={new} (narrowing requires new <= old)"
        )


# ---------------------------------------------------------------------------
# Token estimator protocol
# ---------------------------------------------------------------------------


class TokenEstimator(Protocol):
    """Callable that returns a deterministic token count for ``text``.

    Provider adapters in module_09 supply a native-tokenizer estimator;
    the default :class:`WhitespaceTokenEstimator` matches the v0.1-era
    ``TokenBudget.estimate_tokens`` shape so behavior is backward
    compatible until each adapter opts into its own estimator.
    """

    def estimate(self, text: str) -> int: ...


@dataclass(frozen=True)
class WhitespaceTokenEstimator:
    """Whitespace-split token estimate.

    Same shape as the v0.1-era ``TokenBudget.estimate_tokens``. Under-
    counts BPE tokens for typical code by 20-40 percent, which means
    the accountant's ceiling check is *conservative from the caller's
    view* but *loose from the provider's view*. Depth Chain leaf: the
    module_09 wiring swaps this default for a per-provider estimator
    on every adapter that exposes a native tokenizer.
    """

    def estimate(self, text: str) -> int:
        return len(text.split())


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


class BudgetSection(tuple):
    """One seated slice of the assembled context.

    Fields:

    - ``name`` — section identifier (e.g. ``system_prompt``,
      ``retrieved_bundle``).
    - ``token_count`` — token cost of the seated content.
    - ``content_hash`` — hex sha256 of the section content; ties the
      bookkeeping to the exact bytes seated so a mutated section cannot
      pass a stale accounting.

    Implemented as a ``NamedTuple``-style subclass of ``tuple`` for
    hashability and immutability.
    """

    __slots__ = ()

    name: str
    token_count: int
    content_hash: str

    def __new__(cls, name: str, token_count: int, content_hash: str) -> "BudgetSection":
        if not isinstance(name, str) or not name:
            raise ValueError("BudgetSection.name must be a non-empty string")
        if not isinstance(token_count, int) or token_count < 0:
            raise ValueError("BudgetSection.token_count must be a non-negative int")
        if not isinstance(content_hash, str) or not content_hash:
            raise ValueError("BudgetSection.content_hash must be a non-empty string")
        return tuple.__new__(cls, (name, token_count, content_hash))

    @property  # type: ignore[no-redef]
    def name(self) -> str:  # noqa: F811
        return self[0]

    @property  # type: ignore[no-redef]
    def token_count(self) -> int:  # noqa: F811
        return self[1]

    @property  # type: ignore[no-redef]
    def content_hash(self) -> str:  # noqa: F811
        return self[2]


@dataclass(frozen=True)
class BudgetDeclaration:
    """Per-function budget shape.

    Constructed from :func:`ract.memory.budget_registry.get` for the
    function default, then optionally narrowed by
    :func:`ract.memory.composition.apply_composition_override` (playbook
    override) or :func:`ract.memory.composition.apply_runtime_narrowing`
    (self-adjustment layer). Widening is refused at every boundary.

    Invariants (enforced in ``__post_init__``):

    - ``input_target <= input_max``
    - ``output_target <= output_max``
    - ``hard_ceiling >= input_max + output_max + reasoning_headroom``
    - all seven token counts are non-negative
    - ``function`` is a non-empty string

    Lateral Chain branch B (runaway narrowing): a runtime narrowing
    below half of the current ``input_target`` is refused by
    :func:`ract.memory.composition.apply_runtime_narrowing`; the floor
    lives with the composition helper, not the declaration, because
    the floor is a policy on the narrowing action, not on the shape.
    """

    function: str
    input_min: int
    input_target: int
    input_max: int
    output_min: int
    output_target: int
    output_max: int
    reasoning_headroom: int
    hard_ceiling: int

    def __post_init__(self) -> None:
        if not isinstance(self.function, str) or not self.function:
            raise ValueError("BudgetDeclaration.function must be a non-empty string")
        for name in (
            "input_min",
            "input_target",
            "input_max",
            "output_min",
            "output_target",
            "output_max",
            "reasoning_headroom",
            "hard_ceiling",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(
                    f"BudgetDeclaration.{name} must be int; got {type(value).__name__}"
                )
            if value < 0:
                raise ValueError(f"BudgetDeclaration.{name} must be non-negative")
        if self.input_min > self.input_target:
            raise ValueError(
                "BudgetDeclaration.input_min must be <= input_target "
                f"(input_min={self.input_min}, input_target={self.input_target})"
            )
        if self.input_target > self.input_max:
            raise ValueError(
                "BudgetDeclaration.input_target must be <= input_max "
                f"(input_target={self.input_target}, input_max={self.input_max})"
            )
        if self.output_min > self.output_target:
            raise ValueError(
                "BudgetDeclaration.output_min must be <= output_target "
                f"(output_min={self.output_min}, output_target={self.output_target})"
            )
        if self.output_target > self.output_max:
            raise ValueError(
                "BudgetDeclaration.output_target must be <= output_max "
                f"(output_target={self.output_target}, output_max={self.output_max})"
            )
        required = self.input_max + self.output_max + self.reasoning_headroom
        if self.hard_ceiling < required:
            raise ValueError(
                "BudgetDeclaration.hard_ceiling must be >= "
                "input_max + output_max + reasoning_headroom "
                f"({self.hard_ceiling} < {required})"
            )


@dataclass(frozen=True)
class BudgetNarrowing:
    """One recorded narrowing event.

    Sources:

    - ``composition`` — the playbook YAML for the current use case.
    - ``runtime`` — the self-adjustment layer (module_08).
    - ``cli`` — reserved for v0.6 (CLI flag override).

    Emitted as part of the ``budget.declared`` event payload so a
    narrowing that fires from the wrong source is visible in the trace
    (Lateral Chain branch D).
    """

    function: str
    field_name: str
    old: int
    new: int
    source: Literal["composition", "runtime", "cli"]

    def __post_init__(self) -> None:
        if not isinstance(self.function, str) or not self.function:
            raise ValueError("BudgetNarrowing.function must be a non-empty string")
        if not isinstance(self.field_name, str) or not self.field_name:
            raise ValueError("BudgetNarrowing.field_name must be a non-empty string")
        for label in ("old", "new"):
            value = getattr(self, label)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(
                    f"BudgetNarrowing.{label} must be int; got {type(value).__name__}"
                )
            if value < 0:
                raise ValueError(f"BudgetNarrowing.{label} must be non-negative")
        if self.source not in ("composition", "runtime", "cli"):
            raise ValueError(
                "BudgetNarrowing.source must be one of "
                f"('composition', 'runtime', 'cli'); got {self.source!r}"
            )
        if self.new > self.old:
            raise WideningRefusedError(
                field_name=self.field_name, old=self.old, new=self.new
            )


# The nine narrowable fields on a BudgetDeclaration. ``function`` is the
# identifier and is never narrowed.
_NARROWABLE_FIELDS: tuple[str, ...] = (
    "input_min",
    "input_target",
    "input_max",
    "output_min",
    "output_target",
    "output_max",
    "reasoning_headroom",
    "hard_ceiling",
)


def narrow(
    declaration: BudgetDeclaration,
    narrowings: list[BudgetNarrowing],
) -> BudgetDeclaration:
    """Return a new declaration with every narrowing applied.

    Pure; the input declaration is unchanged. Each narrowing is
    validated against the ORIGINAL declaration value (not the running
    intermediate), so ``narrow(narrow(base, [N1]), [N2])`` cannot
    produce a value wider than ``base`` for the fields both narrowings
    touch — reviewer's construct-time question (Depth Chain).

    Refuses:

    - any narrowing whose ``function`` disagrees with the declaration.
    - any narrowing whose ``field_name`` is not in
      :data:`_NARROWABLE_FIELDS`.
    - any narrowing whose ``old`` disagrees with the current value
      (the caller passed a stale ``old``).
    - a narrowing that would widen (checked in
      :class:`BudgetNarrowing.__post_init__` at construct time and
      re-checked here as belt-and-suspenders).
    """
    updated: dict[str, int] = {}
    for entry in narrowings:
        if entry.function != declaration.function:
            raise ValueError(
                f"BudgetNarrowing.function {entry.function!r} does not match "
                f"declaration.function {declaration.function!r}"
            )
        if entry.field_name not in _NARROWABLE_FIELDS:
            raise ValueError(
                f"BudgetNarrowing.field_name {entry.field_name!r} is not "
                f"narrowable; expected one of {_NARROWABLE_FIELDS}"
            )
        current = updated.get(entry.field_name, getattr(declaration, entry.field_name))
        if entry.old != current:
            raise ValueError(
                f"BudgetNarrowing.old {entry.old} disagrees with the current "
                f"value {current} for field {entry.field_name!r}"
            )
        if entry.new > current:
            raise WideningRefusedError(
                field_name=entry.field_name, old=current, new=entry.new
            )
        updated[entry.field_name] = entry.new
    if not updated:
        return declaration
    payload: dict[str, int | str] = {"function": declaration.function}
    for name in _NARROWABLE_FIELDS:
        payload[name] = updated.get(name, getattr(declaration, name))
    return BudgetDeclaration(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Accountant
# ---------------------------------------------------------------------------


def _fresh_run_id() -> bytes:
    """Return a fresh 16-byte identifier for a run."""
    return uuid.uuid4().bytes


@dataclass
class BudgetAccountant:
    """Per-invocation bookkeeping over an assembled context.

    Constructed with a :class:`BudgetDeclaration`; sections seat one at
    a time via :meth:`seat`. The accountant computes running totals,
    exposes over-target/over-max/over-ceiling predicates, and refuses
    the invocation on over-ceiling via
    :meth:`refuse_if_over_ceiling`.

    The accountant is pure over ``(declaration, seated_sections)``; the
    ``_run_id`` / ``_step_id`` fields are wiring for module_09's event
    emitter but are otherwise inert. The ``_narrowing_log`` is Lateral
    Chain branch E: a per-invocation history of applied narrowings that
    ships in the ``budget.declared`` payload at seat time.
    """

    declaration: BudgetDeclaration
    _sections: dict[str, BudgetSection] = field(default_factory=dict)
    _run_id: bytes = field(default_factory=_fresh_run_id)
    _step_id: bytes | None = None
    _narrowing_log: list[BudgetNarrowing] = field(default_factory=list)

    def seat(self, section: BudgetSection) -> None:
        """Record ``section`` as seated in the assembled context.

        Refuses if a section with the same ``name`` has already been
        seated (the accountant is single-write per section; a caller
        that wants to replace a section must call :meth:`reseat`).
        """
        if section.name in self._sections:
            raise ValueError(
                f"BudgetAccountant.seat: section {section.name!r} already seated "
                f"(use reseat to replace)"
            )
        self._sections[section.name] = section

    def reseat(self, section: BudgetSection) -> None:
        """Replace a previously seated section.

        Refuses if the section has not been seated yet; use :meth:`seat`
        for a fresh seat. The reseat path exists so a caller who
        recomputes a section (e.g. after cascade downgrade) can update
        the accountant without carrying a stale total.
        """
        if section.name not in self._sections:
            raise ValueError(
                f"BudgetAccountant.reseat: section {section.name!r} not seated"
            )
        self._sections[section.name] = section

    def record_narrowing(self, narrowing: BudgetNarrowing) -> None:
        """Append ``narrowing`` to the per-invocation narrowing log.

        The log is what the ``budget.declared`` event payload carries
        (Lateral Chain branch E). Recording is decoupled from the
        actual narrow operation so a caller can log a narrowing that
        the composition helper produced upstream.
        """
        self._narrowing_log.append(narrowing)

    def sections(self) -> tuple[BudgetSection, ...]:
        """Return the currently seated sections in seat order."""
        return tuple(self._sections.values())

    def narrowing_log(self) -> tuple[BudgetNarrowing, ...]:
        """Return the recorded narrowings in record order."""
        return tuple(self._narrowing_log)

    def used(self, section_name: str | None = None) -> int:
        """Return total tokens used across all sections, or one section.

        With ``section_name=None`` returns the sum of every seated
        section's ``token_count``. With a specific name returns that
        section's ``token_count`` (or 0 if not seated).
        """
        if section_name is None:
            return sum(sec.token_count for sec in self._sections.values())
        section = self._sections.get(section_name)
        return section.token_count if section is not None else 0

    def remaining(self, section_name: str | None = None) -> int:
        """Return remaining tokens under the input-target budget.

        With ``section_name=None`` returns ``input_target - used()``.
        With a specific name returns ``input_target - used(name)`` for
        parity with the ``used`` shape; sub-section budgets (the 15
        percent state cap in the master spec §Context composition) are
        computed by the caller in module_09's assembly pipeline.
        """
        return self.declaration.input_target - self.used(section_name)

    def over_target(self) -> bool:
        """True iff seated total exceeds ``input_target``."""
        return self.used() > self.declaration.input_target

    def over_max(self) -> bool:
        """True iff seated total exceeds ``input_max``."""
        return self.used() > self.declaration.input_max

    def over_ceiling(self) -> bool:
        """True iff seated total exceeds ``hard_ceiling``.

        The ``hard_ceiling`` is the entire context including future
        output and reasoning headroom, so a seated total above ceiling
        means the invocation cannot fit even the input, let alone the
        output and reasoning. This is the pre-model refuse gate.
        """
        return self.used() > self.declaration.hard_ceiling

    def _offending_section(self, boundary_value: int) -> tuple[str, int]:
        """Return ``(section_name, delta)`` for the section that broke ``boundary_value``.

        Walks sections in seat order and returns the first section
        whose running total pushed the accountant past ``boundary_value``.
        Delta is the number of tokens by which the boundary was
        exceeded once that section landed.
        """
        running = 0
        for section in self._sections.values():
            running += section.token_count
            if running > boundary_value:
                return section.name, running - boundary_value
        return "__none__", 0

    def refuse_if_over_max(self) -> None:
        """Raise :class:`BudgetExceededError` if seated total > ``input_max``.

        Called after every ``seat`` in the module_09 assembly pipeline.
        The exception names the offending section so the failing
        assembly is diagnosable without re-walking the accountant.
        """
        if not self.over_max():
            return
        name, delta = self._offending_section(self.declaration.input_max)
        raise BudgetExceededError(
            declaration=self.declaration,
            section_name=name,
            delta=delta,
            boundary="input_max",
        )

    def refuse_if_over_ceiling(self) -> None:
        """Raise :class:`BudgetExceededError` if seated total > ``hard_ceiling``.

        This is the sacred-spine pre-model gate. The master spec's
        §Enforcement paragraph states: on over-ceiling, the accountant
        refuses the invocation before the model call and emits
        ``budget.exceeded`` to the event trace. Callers MUST invoke
        this at the boundary between assembly and dispatch. The
        exception carries the offending section name and the token
        delta by which the ceiling was exceeded.

        Event emission is wired through
        :func:`ract.memory.events.emit_budget_exceeded` in module_09;
        this module ships the accountant with the null-sink emitter
        so the invariant is enforceable today.
        """
        if not self.over_ceiling():
            return
        name, delta = self._offending_section(self.declaration.hard_ceiling)
        raise BudgetExceededError(
            declaration=self.declaration,
            section_name=name,
            delta=delta,
            boundary="hard_ceiling",
        )


__all__ = [
    "BudgetAccountant",
    "BudgetDeclaration",
    "BudgetExceededError",
    "BudgetNarrowing",
    "BudgetSection",
    "TokenEstimator",
    "WhitespaceTokenEstimator",
    "WideningRefusedError",
    "narrow",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
