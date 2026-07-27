"""ALM Gate G7 — companion red team.

ALM spec §3.7. The companion is a cold-context second provider that
receives only the intent, the final diff, and the visible predicates
(never the held-out ones, never the event trace, never the model turn
history). Its job is to generate adversarial counterexamples that break
the completion claim. Surviving counterexamples (they pass on the
pre-change workspace and fail on the post-change workspace) emit
``laziness.violated`` with ``kind="companion_counterexample"`` and the
loop resumes with the counterexamples injected into the next planning
prompt.

Router constraint: a companion provider cannot match the primary. The
different-provider rule reads recent-step provider history from
substrate module_05's event trace and refuses to schedule a companion
that overlaps with any of the last three primary steps (lateral chain
branch D: single-provider deployments may opt into advisory mode).

Lateral chain branches merged into this module:

- A: read-only sandbox mount. Companion runs inside a bwrap namespace
  (Linux) or seatbelt (macOS) with the workspace mounted read-only and
  no network egress; findings return via stdout only.
- B: ``time_budget_seconds`` default 120. On timeout the companion
  returns whatever it has so far; the report records
  ``time_exceeded=True``. Below-timeout findings still emit
  ``laziness.violated``; the timeout does not silence the gate.
- C: greenfield-workspace fallback lives on the ``effort`` sibling
  module, not here.
- D: ``CompanionConfig.deployment_mode``; ``single_provider_advisory``
  runs at the same provider and marks findings advisory.

See ADR-0022 for rejected alternatives and
``docs/ARCHITECTURE.md`` "Anti-Lazy Gate G7 (companion red team) and
Gate G8 (effort reconciliation)" for the cross-link into the substrate
architecture.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ract.antilazy.patchdiff import Patch
    from ract.core.predicate import AcceptanceSuite
    from ract.providers.provider import Provider


DeploymentMode = Literal["multi_provider", "single_provider_advisory"]
"""Whether the companion runs at a different provider from the primary.

``multi_provider`` is the default; the router refuses to schedule a
companion whose ``Provider.name`` matches any of the last three
primary steps. ``single_provider_advisory`` acknowledges deployments
that only have one provider account (lateral chain branch D): the
companion runs at the same provider and its findings land in the
report as advisory (``advisory=True``) rather than as hard blocks.
"""


SandboxBackend = Literal["bwrap", "seatbelt", "none"]
"""Which OS sandbox primitive the companion runs inside.

``bwrap`` — Linux ``bubblewrap`` namespace with read-only workspace
mount and no network egress. ``seatbelt`` — macOS ``sandbox-exec``
with the equivalent profile. ``none`` — the sandbox layer is absent
(tests, Windows dev boxes); the caller is responsible for isolating
the companion by other means.
"""


def _default_sandbox_backend() -> SandboxBackend:
    """Return the sandbox backend for the current OS."""
    system = platform.system().lower()
    if system == "linux":
        return "bwrap"
    if system == "darwin":
        return "seatbelt"
    return "none"


# ---------------------------------------------------------------------------
# CounterexampleFinding
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CounterexampleFinding:
    """One counterexample the companion proposes.

    ``test_id`` is a stable identifier for the finding (short slug the
    companion chose). ``test_source`` is the full text of the test file
    the companion proposes running against both pre- and post-change
    workspaces. ``description`` names in plain English what the finding
    claims to show. ``pre_change_pass`` and ``post_change_pass`` record
    what the runner actually observed; a finding is ``surviving`` iff
    it passed pre-change and failed post-change.
    """

    test_id: str
    test_source: str
    description: str
    pre_change_pass: bool = False
    post_change_pass: bool = True
    advisory: bool = False

    def surviving(self) -> bool:
        """True iff the finding passed pre-change and failed post-change."""
        return self.pre_change_pass and not self.post_change_pass


# ---------------------------------------------------------------------------
# CompanionRedTeamReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompanionRedTeamReport:
    """G7 result — the companion's counterexamples plus meta.

    ALM §3.7 report shape. Consumers:

    - ``LoopController`` reads ``surviving_findings()`` on T1 to decide
      whether to emit ``laziness.violated`` and resume the loop.
    - ``COMPANION_MATRIX`` update script reads ``companion_provider``
      to record which pair was actually run.
    - ``advisory`` findings (``deployment_mode="single_provider_advisory"``)
      land on the report but do not enter ``surviving_findings()``.
    """

    companion_provider: str
    primary_provider: str
    counterexamples_generated: int
    counterexamples_that_broke_claim: int
    time_spent_seconds: int
    findings: tuple[CounterexampleFinding, ...] = field(default_factory=tuple)
    time_exceeded: bool = False
    deployment_mode: DeploymentMode = "multi_provider"

    def surviving_findings(self) -> tuple[CounterexampleFinding, ...]:
        """Return non-advisory findings that broke the claim.

        Advisory findings (single-provider-advisory mode) are omitted —
        they log to the report but do not trigger the loop-resume
        pathway.
        """
        return tuple(
            f
            for f in self.findings
            if f.surviving() and not f.advisory
        )

    def advisory_findings(self) -> tuple[CounterexampleFinding, ...]:
        """Return findings marked advisory (single-provider mode)."""
        return tuple(f for f in self.findings if f.advisory)


# ---------------------------------------------------------------------------
# CompanionConfig
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompanionConfig:
    """Configuration for one companion run.

    Frozen dataclass; instances are immutable. Defaults from ALM §3.7
    and the merged lateral chain branches:

    - ``sandbox_backend`` defaults to the platform default
      (``bwrap`` on Linux, ``seatbelt`` on macOS, ``none`` elsewhere).
    - ``read_only`` is always True; the companion never writes to the
      workspace mount (branch A).
    - ``time_budget_seconds`` defaults to 120 seconds (branch B).
    - ``provider`` is required — the companion adapter that produces
      the counterexamples.
    - ``deployment_mode`` defaults to ``multi_provider`` (branch D).
    - ``trivial_rate_ceiling`` closes module_01's flagged gap: the
      composer's rolling trivial rate must not exceed this fraction
      (default 0.3, meaning at most 30% of intents may compose
      trivially before the compiler refuses).
    - ``trivial_rate_window`` names how many recent compositions the
      ceiling reads (default 20).
    """

    provider: "Provider"
    sandbox_backend: SandboxBackend = field(
        default_factory=_default_sandbox_backend
    )
    read_only: bool = True
    time_budget_seconds: int = 120
    deployment_mode: DeploymentMode = "multi_provider"
    trivial_rate_ceiling: float = 0.3
    trivial_rate_window: int = 20

    def __post_init__(self) -> None:
        if not self.read_only:
            raise ValueError(
                "CompanionConfig.read_only must be True; the companion "
                "runs in a read-only workspace mount by design (ALM §3.7 "
                "lateral chain branch A)."
            )
        if self.time_budget_seconds <= 0:
            raise ValueError("time_budget_seconds must be > 0")
        if not 0.0 <= self.trivial_rate_ceiling <= 1.0:
            raise ValueError(
                "trivial_rate_ceiling must be in [0.0, 1.0]; "
                f"got {self.trivial_rate_ceiling}"
            )
        if self.trivial_rate_window <= 0:
            raise ValueError("trivial_rate_window must be > 0")


# ---------------------------------------------------------------------------
# CompanionAdapter protocol — the thing that actually produces findings
# ---------------------------------------------------------------------------


@runtime_checkable
class CompanionAdapter(Protocol):
    """The companion-shaped verb the ALM layer needs.

    Adapters wrap a substrate ``Provider`` (``ract.providers.provider``)
    and translate ``propose_counterexamples(intent, diff, visible)``
    into a specific ``send_planned_step_request`` call whose response is
    parsed as a JSON list of ``CounterexampleFinding`` dicts. Tests
    inject a direct implementation.
    """

    provider_name: str

    def propose_counterexamples(
        self,
        *,
        intent: str,
        diff: "Patch",
        visible_suite: "AcceptanceSuite",
    ) -> tuple[CounterexampleFinding, ...]:
        """Return the counterexamples the adapter proposes.

        The adapter receives ONLY these three inputs. Held-out
        predicates, the event trace, and the primary provider's turn
        history are not passed and must not be smuggled in through
        adapter-internal state.
        """
        ...  # pragma: no cover — protocol


# ---------------------------------------------------------------------------
# CounterexampleRunner protocol — evaluates a finding against two snapshots
# ---------------------------------------------------------------------------


@runtime_checkable
class CounterexampleRunner(Protocol):
    """The runner that evaluates a counterexample on both snapshots.

    Takes a proposed test source and returns whether it passes against
    the pre-change and post-change workspaces. Kept as a protocol so
    tests inject deterministic runners without spawning subprocesses.
    """

    def run(
        self,
        finding: CounterexampleFinding,
        *,
        pre_change_workspace: object,
        post_change_workspace: object,
    ) -> tuple[bool, bool]:
        """Return ``(pre_change_pass, post_change_pass)``."""
        ...  # pragma: no cover — protocol


# ---------------------------------------------------------------------------
# Different-provider constraint
# ---------------------------------------------------------------------------


class CompanionProviderCollisionError(RuntimeError):
    """Raised when the companion matches a recent primary provider.

    ALM §3.7 different-provider constraint. The router calls
    ``enforce_different_provider`` before scheduling the companion; a
    match against any of the last three primary steps' providers raises
    this error. Deployments that opt into
    ``deployment_mode="single_provider_advisory"`` bypass the check via
    ``allow_same_provider=True``.
    """


def enforce_different_provider(
    primary: "Provider",
    companion: "Provider",
    recent_history: tuple[str, ...],
    *,
    allow_same_provider: bool = False,
    window: int = 3,
) -> None:
    """Raise ``CompanionProviderCollisionError`` on a match.

    ``recent_history`` is the tuple of primary-step provider ``name``
    values ordered oldest-to-newest. The last ``window`` entries plus
    the current ``primary`` are checked; any equality with
    ``companion.name`` raises.

    Second Pass adversarial Q1 (first-step provider-history empty
    case): the check ALWAYS compares the companion against the current
    ``primary`` regardless of history length, so step one is still
    guarded even when history is empty. The window scan applies on top.

    ``allow_same_provider`` is the single-provider-advisory escape
    hatch (lateral chain branch D). Callers should pass ``True`` iff
    ``CompanionConfig.deployment_mode == "single_provider_advisory"``.
    """
    if allow_same_provider:
        return
    # Always check the CURRENT primary — this closes the "empty history"
    # hole the Second Pass named on step one of any run.
    if primary.name == companion.name:
        raise CompanionProviderCollisionError(
            f"companion provider {companion.name!r} matches the current "
            "primary provider; the different-provider constraint (ALM "
            "§3.7) refuses this pairing."
        )
    if window <= 0:
        return
    recent = recent_history[-window:] if recent_history else ()
    for prior in recent:
        if prior == companion.name:
            raise CompanionProviderCollisionError(
                f"companion provider {companion.name!r} matches a recent "
                f"primary step provider (last {window} steps: "
                f"{list(recent)!r}); the different-provider constraint "
                "(ALM §3.7) refuses this pairing."
            )


# ---------------------------------------------------------------------------
# run_companion — the top-level entry point
# ---------------------------------------------------------------------------


def run_companion(
    *,
    intent: str,
    diff: "Patch",
    visible_suite: "AcceptanceSuite",
    config: CompanionConfig,
    adapter: CompanionAdapter,
    runner: CounterexampleRunner | None = None,
    pre_change_workspace: object | None = None,
    post_change_workspace: object | None = None,
    primary: "Provider | None" = None,
    recent_history: tuple[str, ...] = (),
) -> CompanionRedTeamReport:
    """Run the companion red team and return a ``CompanionRedTeamReport``.

    ``adapter`` is the companion-shaped verb (adapters wrap a
    substrate ``Provider``); ``runner`` evaluates each proposed
    counterexample against both snapshots. If ``runner`` is ``None``
    the findings are returned unrun (``pre_change_pass=False``,
    ``post_change_pass=True``) and ``surviving_findings()`` is empty —
    a caller that skips the runner is opting out of the loop-resume
    pathway.

    The different-provider constraint (branch D and Second Pass Q1) is
    enforced here when ``primary`` is provided. Callers with only one
    provider account pass
    ``config.deployment_mode="single_provider_advisory"`` and get an
    advisory-only report.
    """
    import time as _time

    start = _time.monotonic()

    # Different-provider constraint (Second Pass Q1). Runs BEFORE the
    # adapter dispatch so a collision never wastes a companion call.
    if primary is not None:
        allow_same = config.deployment_mode == "single_provider_advisory"
        enforce_different_provider(
            primary,
            _AdapterAsProvider(adapter),  # type: ignore[arg-type]
            recent_history,
            allow_same_provider=allow_same,
        )

    # Dispatch the adapter — with a wall-clock budget per lateral chain
    # branch B. On timeout we return whatever findings the adapter
    # produced so far; the report records ``time_exceeded=True`` so
    # the operator can widen the budget or investigate.
    proposed: tuple[CounterexampleFinding, ...] = ()
    time_exceeded = False
    try:
        proposed = adapter.propose_counterexamples(
            intent=intent, diff=diff, visible_suite=visible_suite
        )
    except _CompanionTimeout:
        time_exceeded = True
    # Second Pass fix (module_04 Second Pass, external reviewer
    # Additional Defect #3): elapsed is computed once at the end of
    # all work and both the ``time_exceeded`` flag and
    # ``time_spent_seconds`` derive from the same measurement. The
    # earlier version had an adapter-scoped elapsed and a total
    # elapsed that could produce ``time_spent_seconds > budget`` while
    # ``time_exceeded=True`` was asserted against a smaller number,
    # which read as internally inconsistent in the report.

    # Evaluate each finding against both snapshots (branch A: the
    # runner is expected to load the workspaces read-only).
    is_advisory = config.deployment_mode == "single_provider_advisory"
    evaluated: list[CounterexampleFinding] = []
    for finding in proposed:
        if runner is None or pre_change_workspace is None or post_change_workspace is None:
            evaluated.append(
                CounterexampleFinding(
                    test_id=finding.test_id,
                    test_source=finding.test_source,
                    description=finding.description,
                    pre_change_pass=finding.pre_change_pass,
                    post_change_pass=finding.post_change_pass,
                    advisory=is_advisory,
                )
            )
            continue
        pre_ok, post_ok = runner.run(
            finding,
            pre_change_workspace=pre_change_workspace,
            post_change_workspace=post_change_workspace,
        )
        evaluated.append(
            CounterexampleFinding(
                test_id=finding.test_id,
                test_source=finding.test_source,
                description=finding.description,
                pre_change_pass=pre_ok,
                post_change_pass=post_ok,
                advisory=is_advisory,
            )
        )

    survivors_count = sum(
        1 for f in evaluated if f.surviving() and not f.advisory
    )
    total_elapsed_seconds = max(0.0, _time.monotonic() - start)
    total_elapsed_int = int(total_elapsed_seconds)
    # Budget check runs against the SAME measurement as the report so
    # ``time_spent_seconds`` and ``time_exceeded`` never disagree.
    if total_elapsed_seconds > config.time_budget_seconds:
        time_exceeded = True
    report = CompanionRedTeamReport(
        companion_provider=adapter.provider_name,
        primary_provider=primary.name if primary is not None else "",
        counterexamples_generated=len(evaluated),
        counterexamples_that_broke_claim=survivors_count,
        time_spent_seconds=total_elapsed_int,
        findings=tuple(evaluated),
        time_exceeded=time_exceeded,
        deployment_mode=config.deployment_mode,
    )
    # Best-effort trace emission on surviving (non-advisory) findings.
    if survivors_count > 0:
        try:  # local import breaks the trace→antilazy cycle
            from ract.trace.sink import emit as _emit_event

            sample = next(
                (f for f in evaluated if f.surviving() and not f.advisory),
                None,
            )
            _emit_event(
                "laziness.violated",
                {
                    "kind": "companion_counterexample",
                    "companion_provider": adapter.provider_name,
                    "primary_provider": primary.name if primary is not None else "",
                    "counterexamples_generated": len(evaluated),
                    "counterexamples_that_broke_claim": survivors_count,
                    "time_exceeded": time_exceeded,
                    "sample_test_id": sample.test_id if sample else "",
                    "sample_description": sample.description if sample else "",
                    "deployment_mode": config.deployment_mode,
                },
            )
        except Exception:  # noqa: BLE001 — never fail the gate on trace error
            pass
    return report


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _CompanionTimeout(RuntimeError):
    """Adapter internal signal — companion aborted on time budget."""


class _AdapterAsProvider:
    """Adapter shim so ``enforce_different_provider`` sees a ``Provider``.

    The adapter carries ``provider_name`` (the wire-level provider
    identity); the constraint check only reads ``.name``. A separate
    class keeps the ``Provider`` protocol surface unmixed with the
    ALM-level ``CompanionAdapter`` protocol.
    """

    def __init__(self, adapter: CompanionAdapter) -> None:
        self._adapter = adapter

    @property
    def name(self) -> str:
        return self._adapter.provider_name


__all__ = [
    "CompanionAdapter",
    "CompanionConfig",
    "CompanionProviderCollisionError",
    "CompanionRedTeamReport",
    "CounterexampleFinding",
    "CounterexampleRunner",
    "DeploymentMode",
    "SandboxBackend",
    "enforce_different_provider",
    "run_companion",
]


# RACT 0.4.0
