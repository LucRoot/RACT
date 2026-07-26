"""Substrate step-loop: worktree-per-step transaction orchestration.

SUBSTRATE spec §3. This is the loop that turns a plan into a schedule
over transactions. Each step:

1. Opens a worktree off ``parent_snapshot``.
2. Optionally launches a container mounting the worktree (module_03 will
   land the sandbox inside).
3. Runs the step's actions inside that isolated pair via a caller-supplied
   ``step_runner`` (kept external so this module has no dependency on
   ``providers`` and stays trivially testable).
4. Evaluates the transaction's post-conditions against a
   ``WorkspaceSnapshot`` reflecting the worktree (module_01's predicate
   substrate).
5. On success (all required post-conditions ``ok=True``): commits the
   worktree changes to the step branch and advances the loop's
   ``parent_snapshot`` to the new commit sha.
6. On failure or an unresolved blocking handshake: rolls back (or in the
   handshake case, leaves the worktree intact for operator inspection)
   and the next step retries from the last good snapshot.

The plan reduces to a schedule; the workspace snapshot chain is the
durable artifact.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ract.core.loop import WorkspaceSnapshot
from ract.core.transaction import (
    ContainerRef,
    ResourceBudget,
    StepTransaction,
    TransactionOutcome,
    new_step_id,
    open_transaction,
)
from ract.executor.runtime import ContainerBackend
from ract.executor.worktree import Worktree, WorktreeManager
from ract.handshake_registry import HandshakeRegistry
from ract.security.manifest import CapabilityManifest
from ract.security.sandbox import SandboxBackend


# ---------------------------------------------------------------------------
# Step spec + record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubstrateStepSpec:
    """One planned step in the transactional schedule.

    ``predicates`` are the post-conditions the transaction commits on.
    ``runtime_image`` is optional; ``None`` opts out of container isolation
    for this step (worktree-only). ``handshake_ids`` names any handshakes
    whose resolution this step depends on — the transaction returns
    ``BLOCKED_ON_HANDSHAKE`` if any is unresolved at commit time.
    """

    step_id: bytes = field(default_factory=new_step_id)
    predicates: tuple = ()  # tuple[AcceptancePredicate, ...]
    runtime_image: str | None = None
    budget: ResourceBudget = field(default_factory=ResourceBudget)
    handshake_ids: tuple[str, ...] = ()
    depends_on: tuple[bytes, ...] = ()
    commit_message: str = ""


@dataclass(frozen=True)
class StepRecord:
    """Terminal outcome of one substrate step transaction."""

    step_id: bytes
    outcome: TransactionOutcome
    parent_snapshot_before: str
    parent_snapshot_after: str
    branch: str
    reason: str = ""


# The step runner is a caller-supplied callable that performs the actual
# work inside the worktree. Kept as a plain callable so this module has
# no dependency on providers, plans, or Rooted values.
StepRunner = Callable[[Worktree, ContainerRef | None], WorkspaceSnapshot]


# ---------------------------------------------------------------------------
# SubstrateLoop
# ---------------------------------------------------------------------------


class SubstrateLoop:
    """Drive a sequence of ``SubstrateStepSpec`` values as transactions."""

    def __init__(
        self,
        *,
        repo_root: Path,
        parent_snapshot: str,
        worktree_manager: WorktreeManager | None = None,
        container_backend: ContainerBackend | None = None,
        handshake_registry: HandshakeRegistry | None = None,
        manifest: CapabilityManifest | None = None,
        sandbox_backend: SandboxBackend | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.parent_snapshot = parent_snapshot
        self.worktrees = worktree_manager or WorktreeManager(repo_root)
        self.container_backend = container_backend
        self.handshakes = handshake_registry
        # module_03 (SUBSTRATE §4): the loop carries the run's capability
        # manifest and the resolved sandbox backend. On Windows the caller
        # may pass ``sandbox_backend=UnenforcedSandbox()`` after honoring
        # the ``--allow-unenforced-sandbox`` flag; the loop will still
        # enter the (no-op) sandbox so the call site exists and
        # ``sandbox.unenforced`` fires into the event log.
        self.manifest = manifest
        self.sandbox_backend = sandbox_backend
        self.records: list[StepRecord] = []
        # Track committed step_ids so ``depends_on`` can gate downstream
        # commits without leaking the plan graph into git.
        self._committed_step_ids: set[bytes] = set()

    # ---- one step -------------------------------------------------------

    def run_step(
        self, spec: SubstrateStepSpec, step_runner: StepRunner
    ) -> StepRecord:
        """Open the transaction, run the step, evaluate post-conditions, commit
        or roll back.

        ``step_runner(worktree, container_ref)`` performs the actual work
        inside the worktree and returns a ``WorkspaceSnapshot`` used to
        evaluate the post-conditions.
        """
        parent_before = self.parent_snapshot

        # ---- depends_on gate ----------------------------------------------
        for dep in spec.depends_on:
            if dep not in self._committed_step_ids:
                record = StepRecord(
                    step_id=spec.step_id,
                    outcome=TransactionOutcome.BLOCKED_ON_HANDSHAKE,
                    parent_snapshot_before=parent_before,
                    parent_snapshot_after=parent_before,
                    branch=f"rootact/step/{spec.step_id.hex()}",
                    reason=f"blocked on prior step {dep.hex()}",
                )
                self.records.append(record)
                return record

        # ---- open worktree + (maybe) container ----------------------------
        wt = self.worktrees.create(spec.step_id, parent_before)
        container: ContainerRef | None = None
        try:
            if spec.runtime_image is not None and self.container_backend is not None:
                container = self.container_backend.start(
                    image=spec.runtime_image,
                    worktree_path=wt.path,
                    budget=spec.budget,
                )

            txn = open_transaction(
                step_id=spec.step_id,
                parent_snapshot=parent_before,
                worktree_path=wt.path,
                postconditions=tuple(spec.predicates),
                timeout_seconds=spec.budget.wall_seconds,
                budget=spec.budget,
                runtime_container=container,
                depends_on=spec.depends_on,
                manifest=self.manifest,
            )

            # module_03: enter the OS-enforced sandbox for this step.
            # A manifest-less loop skips sandbox entry entirely so v0.3
            # tests still pass while the SubstrateLoop-as-default
            # migration is pending (see module_02 flagged gaps).
            if self.manifest is not None and self.sandbox_backend is not None:
                with self.sandbox_backend.enter(
                    self.manifest,
                    wt.path,
                    container,
                    step_id=spec.step_id,
                ):
                    snapshot = step_runner(wt, container)
            else:
                snapshot = step_runner(wt, container)
            record = self._finalize(txn, wt, snapshot, spec)
            return record
        finally:
            if container is not None and self.container_backend is not None:
                self.container_backend.stop(container)

    # ---- finalize -------------------------------------------------------

    def _finalize(
        self,
        txn: StepTransaction,
        wt: Worktree,
        snapshot: WorkspaceSnapshot,
        spec: SubstrateStepSpec,
    ) -> StepRecord:
        parent_before = txn.parent_snapshot

        # Evaluate post-conditions first — the handshake block only matters
        # if the step would have committed.
        for predicate in txn.postconditions:
            if not predicate.required:
                continue
            result = predicate.evaluate(snapshot)
            if not result.ok:
                self.worktrees.rollback(wt, abandon=False)
                record = StepRecord(
                    step_id=txn.step_id,
                    outcome=TransactionOutcome.ROLLED_BACK,
                    parent_snapshot_before=parent_before,
                    parent_snapshot_after=parent_before,
                    branch=wt.branch,
                    reason=f"post-condition failed: {result.reason}",
                )
                self.records.append(record)
                return record

        # Handshake gate: post-conditions passed, but if any declared
        # handshake is unresolved we hold the worktree open for operator
        # inspection and refuse to advance the parent snapshot.
        if spec.handshake_ids and self.handshakes is not None:
            pending_ids = {item.id for item in self.handshakes.pending()}
            unresolved = [hid for hid in spec.handshake_ids if hid in pending_ids]
            if unresolved:
                record = StepRecord(
                    step_id=txn.step_id,
                    outcome=TransactionOutcome.BLOCKED_ON_HANDSHAKE,
                    parent_snapshot_before=parent_before,
                    parent_snapshot_after=parent_before,
                    branch=wt.branch,
                    reason=(
                        "post-conditions ok; commit blocked on handshake "
                        f"{unresolved!r}"
                    ),
                )
                self.records.append(record)
                # Deliberately do NOT roll back — the worktree stays intact.
                return record

        # Commit the worktree changes to the step branch. Advance the
        # parent-snapshot pointer to the new commit.
        message = spec.commit_message or f"rootact step {txn.step_id.hex()}"
        try:
            new_sha = self.worktrees.commit(wt, message)
        except Exception as exc:  # noqa: BLE001 — rollback on any commit failure
            self.worktrees.rollback(wt, abandon=False)
            record = StepRecord(
                step_id=txn.step_id,
                outcome=TransactionOutcome.ROLLED_BACK,
                parent_snapshot_before=parent_before,
                parent_snapshot_after=parent_before,
                branch=wt.branch,
                reason=f"commit failed: {exc}",
            )
            self.records.append(record)
            return record

        # Update the loop's canonical HEAD to reference the step-branch
        # commit. We do this by fast-forwarding the repo's checked-out
        # branch to the step-branch tip. If the repo has uncommitted
        # working-tree state we skip the fast-forward (the constructor
        # already refused a dirty tree at loop entry, but tests may build
        # a manager without going through the constructor).
        _fast_forward_head(self.repo_root, new_sha)
        self.parent_snapshot = new_sha
        self._committed_step_ids.add(txn.step_id)

        # Committed transaction: prune the worktree tree (branch survives).
        _remove_worktree_only(self.repo_root, wt.path)

        record = StepRecord(
            step_id=txn.step_id,
            outcome=TransactionOutcome.COMMITTED,
            parent_snapshot_before=parent_before,
            parent_snapshot_after=new_sha,
            branch=wt.branch,
        )
        self.records.append(record)
        return record


# ---------------------------------------------------------------------------
# Small git helpers used by SubstrateLoop only
# ---------------------------------------------------------------------------


def _fast_forward_head(repo_root: Path, new_sha: str) -> None:
    """Advance the repo's HEAD-branch tip to ``new_sha`` when it is an ancestor.

    We refuse to force-move HEAD; this only fires when ``new_sha``'s
    history contains the current HEAD. A step that produced a divergent
    branch leaves HEAD alone and the plan graph will surface the
    divergence via ``ract session ls``.
    """
    is_ancestor = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "merge-base",
            "--is-ancestor",
            "HEAD",
            new_sha,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if is_ancestor.returncode != 0:
        return
    subprocess.run(
        ["git", "-C", str(repo_root), "reset", "--hard", new_sha],
        capture_output=True,
        text=True,
        check=False,
    )


def _remove_worktree_only(repo_root: Path, worktree_path: Path) -> None:
    """Remove the worktree directory but leave the branch intact."""
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "worktree",
            "remove",
            "--force",
            str(worktree_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


# RACT 0.4.0
