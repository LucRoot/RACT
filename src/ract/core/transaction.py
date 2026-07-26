"""Step-level transactions — worktree-per-step, container-per-step.

SUBSTRATE spec §3 (Substrate Layer 2: Transactional Execution) and §11
signal 3. The workspace is the durable artifact; the plan is an ephemeral
schedule over transactions. Every step opens a ``StepTransaction``:

- Code isolation comes from a ``git worktree`` on a step-specific branch
  named ``rootact/step/<step_id_hex>`` (see ``git-worktree`` public
  documentation at ``https://git-scm.com/docs/git-worktree``; the
  branch-per-worktree idiom is the same pattern Claude Code subagents use
  when invoked with ``isolation: worktree``).
- Runtime isolation, when requested, comes from a container per worktree
  (see the Dagger Container Use README at
  ``https://github.com/dagger/container-use``). The container backend is
  optional per step; a step whose ``runtime_container`` is ``None`` runs
  in the worktree only. Sandbox hardening is deferred to module_03.
- Commit / rollback semantics follow the workflow-versus-activity split
  from the Temporal durable-execution model
  (``https://docs.temporal.io/``): the loop describes what "done" looks
  like (post-conditions from module_01); each step is an activity whose
  outcome is recorded (``TransactionOutcome``).

Design rationale in ``docs/ADRs/ADR-0011-worktree-per-step.md``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from ract.core.predicate import AcceptancePredicate
from ract.core.types import Digest


# ---------------------------------------------------------------------------
# Small primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceBudget:
    """Bounds on a single step transaction's resource envelope.

    ``cpu`` is a fractional CPU count (``1.0`` = one core). ``memory_mb`` is
    a soft cap; the executor may enforce a matching cgroup / Job-Object
    limit if the runtime supports it. ``network`` is a coarse toggle for
    module_03's manifest to refine; ``wall_seconds`` is the hard timeout.
    """

    cpu: float = 1.0
    memory_mb: int = 1024
    network: bool = False
    wall_seconds: int = 60

    def __post_init__(self) -> None:
        if self.cpu <= 0.0:
            raise ValueError("cpu must be > 0")
        if self.memory_mb <= 0:
            raise ValueError("memory_mb must be > 0")
        if self.wall_seconds <= 0:
            raise ValueError("wall_seconds must be > 0")


@dataclass(frozen=True)
class ContainerRef:
    """Handle to a running (or startable) container mounting the worktree.

    ``backend`` names which ``ContainerBackend`` produced this reference;
    ``id`` is an opaque string the backend uses to stop the container.
    Kept minimal on purpose — module_03's capability manifest carries the
    sandbox contract.
    """

    backend: str
    id: str
    image: str = ""


class TransactionOutcome(Enum):
    """Terminal state of a ``StepTransaction``."""

    COMMITTED = auto()
    ROLLED_BACK = auto()
    BLOCKED_ON_HANDSHAKE = auto()


# ---------------------------------------------------------------------------
# StepTransaction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepTransaction:
    """One step's isolated write scope.

    ``parent_snapshot`` is the git commit sha the worktree was created
    from; on ``COMMITTED`` the loop advances its parent-snapshot pointer
    to the new commit sha (returned by ``commit_or_rollback``). On
    ``ROLLED_BACK`` the worktree and container are torn down and the
    workspace returns to its prior state. On ``BLOCKED_ON_HANDSHAKE`` the
    worktree stays intact for operator inspection but the parent snapshot
    is not advanced.
    """

    step_id: bytes
    parent_snapshot: str
    worktree_path: Path
    postconditions: tuple[AcceptancePredicate, ...]
    timeout_seconds: int
    budget: ResourceBudget
    runtime_container: ContainerRef | None = None
    depends_on: tuple[bytes, ...] = field(default_factory=tuple)
    # module_03 (SUBSTRATE §4): every transaction opens inside a sandbox
    # derived from the run's ``CapabilityManifest``. The digest here is
    # what module_05's event log joins to the manifest and what module_06
    # will stamp into the extended Rootknot as ``manifest_digest``. Kept
    # as ``Digest | None`` so v0.3 call sites still construct valid
    # transactions during the SubstrateLoop-as-default migration.
    manifest_digest: Digest | None = None

    def __post_init__(self) -> None:
        if len(self.step_id) != 16:
            raise ValueError("step_id must be a 16-byte UUID")
        if not self.parent_snapshot:
            raise ValueError("parent_snapshot must be a non-empty git sha")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        for dep in self.depends_on:
            if len(dep) != 16:
                raise ValueError("each dependency step_id must be a 16-byte UUID")

    @property
    def branch_name(self) -> str:
        """The canonical step-branch name (asserted by the property tests)."""
        return f"rootact/step/{self.step_id.hex()}"


def new_step_id() -> bytes:
    """Return a fresh 16-byte identifier for a step transaction."""
    return uuid.uuid4().bytes


# ---------------------------------------------------------------------------
# open / commit_or_rollback
# ---------------------------------------------------------------------------


def open_transaction(
    *,
    step_id: bytes,
    parent_snapshot: str,
    worktree_path: Path,
    postconditions: tuple[AcceptancePredicate, ...] = (),
    timeout_seconds: int = 60,
    budget: ResourceBudget | None = None,
    runtime_container: ContainerRef | None = None,
    depends_on: tuple[bytes, ...] = (),
    manifest: object | None = None,
) -> StepTransaction:
    """Build a ``StepTransaction`` value.

    Actually opening the worktree and (optionally) launching the container
    is the caller's responsibility — see
    ``ract.executor.worktree.create_worktree`` and
    ``ract.executor.runtime.ContainerBackend.start``. This factory only
    stitches the descriptors together so the transaction is a value the
    loop can pass around and reason about.
    """
    # ``manifest`` is typed ``object | None`` here (rather than
    # ``CapabilityManifest | None``) so the substrate primitive does not
    # take a hard runtime import on ``ract.security.manifest`` — that
    # would create a cycle when the security layer eventually imports
    # types from this module. The digest is computed locally when a
    # manifest is passed; both branches produce a valid transaction.
    digest: Digest | None = None
    if manifest is not None:
        from ract.security.manifest import CapabilityManifest, ManifestDigest

        if not isinstance(manifest, CapabilityManifest):
            raise TypeError(
                "manifest must be a ract.security.manifest.CapabilityManifest"
            )
        digest = ManifestDigest.of(manifest)
    txn = StepTransaction(
        step_id=step_id,
        parent_snapshot=parent_snapshot,
        worktree_path=Path(worktree_path),
        postconditions=tuple(postconditions),
        timeout_seconds=timeout_seconds,
        budget=budget if budget is not None else ResourceBudget(),
        runtime_container=runtime_container,
        depends_on=tuple(depends_on),
        manifest_digest=digest,
    )
    # module_05: emit step.started at the transaction-open site so the
    # event log's step timeline is derivable from the loop even when
    # the loop's driver code is out of scope (a caller building a
    # transaction directly still gets a durable start marker).
    try:  # local import breaks the trace→core cycle at import time
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "step.started",
            {
                "parent_snapshot": txn.parent_snapshot,
                "branch": txn.branch_name,
                "postcondition_count": len(txn.postconditions),
                "manifest_digest": (
                    txn.manifest_digest.hex()
                    if txn.manifest_digest is not None
                    else None
                ),
                "timeout_seconds": txn.timeout_seconds,
            },
            step_id=txn.step_id,
        )
    except Exception:  # noqa: BLE001 — never fail transaction open on trace error
        pass
    return txn


# RACT 0.4.0
