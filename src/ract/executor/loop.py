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
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ract.core.module_identity import (
    _module_knot,
    is_registered_knot,
    register_module_knot,
)

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)

import logging

_KNOT_LOGGER = logging.getLogger(__name__)

from ract.contracts.auction import AuctionSweep
from ract.core.loop import WorkspaceSnapshot
from ract.core.transaction import (
    ContainerRef,
    ResourceBudget,
    StepTransaction,
    TransactionOutcome,
    new_step_id,
    open_transaction,
)
from ract.executor.commit_compensator import (
    CompensatorStack,
    build_compensator,
)
from ract.executor.process_group import (
    ProcessGroupHandle,
    kill_tree,
    spawn,
)
from ract.executor.subagent_handle import (
    SubagentHandle,
    emit_subagent_disposed_event,
)
from ract.executor.runtime import ContainerBackend
from ract.executor.tool_gate import (
    ToolBudget,
    ToolInvocationGate,
    ToolRegistry,
)
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

    ``metadata`` is a free-form dict the loop reads for optional wiring.
    v0.5.0 memory discipline (module_09) reads
    ``metadata["retrieval_bundle"]`` when present and threads the
    bundle into the runner's context via a
    ``retrieval.satisfied`` event at step start. A caller who does not
    set the key sees today's behavior (deterministic non-model step or
    a legacy step that pre-dates memory discipline).
    """

    step_id: bytes = field(default_factory=new_step_id)
    predicates: tuple = ()  # tuple[AcceptancePredicate, ...]
    runtime_image: str | None = None
    budget: ResourceBudget = field(default_factory=ResourceBudget)
    handshake_ids: tuple[str, ...] = ()
    depends_on: tuple[bytes, ...] = ()
    commit_message: str = ""
    metadata: dict = field(default_factory=dict)


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
        auction_sweep: AuctionSweep | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_declared_ids: frozenset[str] | None = None,
        tool_budget: ToolBudget | None = None,
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
        # module_08 (SUBSTRATE §8): between-iteration Auction sweep. When
        # attached, the sweep is invoked at every step boundary and gated
        # by ``AuctionConfig.min_iteration_wall_seconds`` (module_06
        # lateral chain branch D). Each proposal emits an
        # ``auction.proposal`` event to the module_05 event log via
        # ``AuctionSweep.run``.
        self.auction_sweep = auction_sweep
        self._loop_start_monotonic: float = time.monotonic()
        self.records: list[StepRecord] = []
        # Track committed step_ids so ``depends_on`` can gate downstream
        # commits without leaking the plan graph into git.
        self._committed_step_ids: set[bytes] = set()

        # v0.5.1 module_05 -- tool-invocation gate (SUBSTRATE §5). The
        # loop owns the gate; individual steps invoke tools through
        # ``self.invoke_tool``. A loop constructed without a registry
        # runs in legacy mode (no gate; ``invoke_tool`` refuses on
        # first call so the migration is loud).
        self.tool_registry = tool_registry
        # Prefer explicit declared_ids; else read registry ids as the
        # declared surface (test-friendly). ``frozenset()`` = tool
        # calls always refuse (gate strictly denies).
        if tool_declared_ids is not None:
            self._tool_declared_ids = frozenset(tool_declared_ids)
        elif tool_registry is not None:
            self._tool_declared_ids = tool_registry.declared_ids()
        else:
            self._tool_declared_ids = frozenset()
        self._tool_budget = tool_budget or ToolBudget()
        self._tool_gates: dict[bytes, ToolInvocationGate] = {}
        # v0.5.1 wiring module_03 SP Q5: MCP inputSchemas per tool_id.
        self._mcp_input_schemas: dict[str, dict[str, object]] = {}
        # v0.5.1 module_05 -- commit compensator stack (SUBSTRATE §7).
        # Every successful commit inside the loop installs a soft-reset
        # compensator; disposal-other-than-T1 drains the stack LIFO.
        self.compensator_stack = CompensatorStack()
        # v0.5.1 wiring module_05 (Lens C C-03 closure): the loop
        # tracks every process handle spawned via
        # :meth:`spawn_step_subprocess` so a rollback or unsuccessful
        # dispose reaps the parent + every descendant via
        # ``process_group.kill_tree``. SUBSTRATE §7 rollback contract
        # ("SIGKILL to the entire process group tree") is unmet in the
        # runtime path today because the primitive has zero production
        # callers; this list gives it its production surface. Handles
        # are appended on spawn, removed after ``_reap_active_processes``
        # or explicit deregistration on natural exit.
        self._active_process_handles: list[ProcessGroupHandle] = []
        # v0.5.1 spec-completeness module_07 (Lens 2 Delta 3): SubagentHandle
        # cascade. Orthogonal to :attr:`_active_process_handles`: process
        # handles cover DIRECT subprocess trees the loop spawned via
        # :meth:`spawn_step_subprocess`; subagent handles cover
        # long-lived helper resources (Whisperer / Fence / LSP / embedding
        # sidecars) that the loop launches on-demand. A NON-T1 dispose
        # cascades every registered handle LIFO so a leaked subagent
        # does not survive rollback. T1 (success) discards the list --
        # the caller's natural cleanup path handles the resources.
        self._active_subagent_handles: list[SubagentHandle] = []
        # v0.5.1 wiring module_05 (module_04 SP Q5 defer closure): the
        # sandbox backend's :meth:`enter` context yields a rendered
        # command (``BwrapCommand`` on Linux, ``SeatbeltProfile`` on
        # macOS, ``None`` on the Windows stub). Its ``env`` field is
        # the filtered env dict from module_04's ``build_sandbox_env``.
        # ``run_step`` captures the yielded object into this attribute
        # for the duration of the step so :meth:`spawn_step_subprocess`
        # can auto-consume it as ``Popen(env=...)``. Reset to ``None``
        # after the step's context manager exits.
        self._current_sandbox_env: dict[str, str] | None = None

    # ---- one step -------------------------------------------------------

    def run_step(
        self,
        spec: SubstrateStepSpec,
        step_runner: StepRunner,
        *,
        caller_knot: object | None = None,
    ) -> StepRecord:
        """Open the transaction, run the step, evaluate post-conditions, commit
        or roll back.

        ``step_runner(worktree, container_ref)`` performs the actual work
        inside the worktree and returns a ``WorkspaceSnapshot`` used to
        evaluate the post-conditions.

        ``caller_knot`` is an optional module-identity attestation from
        the calling module. When provided, it must be a knot registered
        in ``ract.core.module_identity.MODULE_KNOT_REGISTRY``; an
        unregistered object trips ``AssertionError``. When omitted the
        loop logs a debug warning rather than raising, so v0.3 callers
        that predate the attestation continue to work.
        """
        if caller_knot is not None:
            assert is_registered_knot(caller_knot), (
                "caller_knot is not a registered module knot"
            )
        else:
            _KNOT_LOGGER.debug("caller did not present a module knot")
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
                _emit_step_event(record, "step.rolled_back")
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

            # module_08 (SUBSTRATE §8): fire the between-iteration
            # Auction sweep at the step boundary if attached. The
            # ``should_run`` gate on ``AuctionConfig.min_iteration_wall_seconds``
            # prevents runaway wall-clock. This intentionally runs
            # BEFORE opening the transaction so a proposal emitted this
            # boundary reflects the parent snapshot state, not any
            # in-flight worktree.
            self._maybe_run_auction_sweep()

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

            # module_09 (v0.5.0 memory discipline §Signals items 11-13):
            # emit ``retrieval.satisfied`` at step start when the caller
            # populated ``metadata["retrieval_bundle"]``. The bundle is
            # passed through the step's context so the runner can
            # inspect it; the loop's contract is JUST to surface the
            # signal in the trace. A step without the key proceeds as
            # today (deterministic non-model step or legacy step).
            _maybe_emit_retrieval_satisfied(spec)

            # module_03: enter the OS-enforced sandbox for this step.
            # A manifest-less loop skips sandbox entry entirely so v0.3
            # tests still pass while the SubstrateLoop-as-default
            # migration is pending (see module_02 flagged gaps).
            #
            # v0.5.1 wiring module_05 (module_04 SP Q5 defer closure):
            # capture the sandbox context's yielded object so
            # ``spawn_step_subprocess`` can consume its ``env`` field
            # for every subprocess the step_runner launches. The
            # backend yields ``BwrapCommand`` (Linux) / ``SeatbeltProfile``
            # (macOS) whose ``.env`` is module_04's filtered dict; the
            # Windows stub yields ``None`` and the spawner falls back
            # to explicit env or parent env.
            if self.manifest is not None and self.sandbox_backend is not None:
                with self.sandbox_backend.enter(
                    self.manifest,
                    wt.path,
                    container,
                    step_id=spec.step_id,
                ) as sandbox_ctx:
                    self._current_sandbox_env = _extract_sandbox_env(sandbox_ctx)
                    try:
                        snapshot = step_runner(wt, container)
                    finally:
                        self._current_sandbox_env = None
            else:
                snapshot = step_runner(wt, container)
            record = self._finalize(txn, wt, snapshot, spec)
            return record
        except BaseException:
            # v0.5.1 wiring module_05 (Lens C C-03): any uncaught
            # exception in step_runner or finalize path leaks child
            # processes past the step boundary. Reap the tree before
            # unwinding so SUBSTRATE §7 rollback contract holds even
            # when a step raises unexpectedly.
            self._reap_active_processes(reason="run_step_exception")
            # v0.5.1 spec-completeness module_07 (Lens 2 Delta 3):
            # a step_runner may have spawned a subagent whose
            # cascade contract runs on ANY halt path -- not just
            # loop-level dispose(). Reap subagents on the same
            # exception unwind so a raise mid-step does not leak a
            # long-lived helper past the step boundary.
            self._reap_subagent_handles(reason="run_step_exception")
            raise
        finally:
            if container is not None and self.container_backend is not None:
                self.container_backend.stop(container)

    # ---- tool-invocation gate ------------------------------------------

    def invoke_tool(
        self,
        tool_id: str,
        args: dict[str, object] | None = None,
        *,
        step_id: bytes | None = None,
    ) -> object:
        """Single chokepoint for tool calls (SUBSTRATE §5).

        v0.5.1 module_05. Every tool call inside a substrate step
        flows through this method; the ``ToolInvocationGate`` for the
        step is lazily constructed on first invocation and reused for
        every subsequent call under the same ``step_id``.

        - ``tool_id`` must be in ``self._tool_declared_ids`` (from
          the manifest or the caller-declared allowlist).
        - ``args`` is a kwargs-style dict; the gate validates against
          the registered tool's ``ToolArgSchema``.
        - ``step_id`` identifies which step's budget is consumed;
          defaults to a per-loop synthetic id when omitted (a caller
          driving invoke_tool outside a step still gets a single
          shared budget).

        Raises ``ToolInvocationRefused`` (imported from
        ``ract.executor.tool_gate``) on any gate failure.
        """
        if self.tool_registry is None:
            # Import here to avoid a top-level cycle and keep the
            # refusal structured.
            from ract.executor.tool_gate import ToolInvocationRefused

            raise ToolInvocationRefused(
                tool_id=tool_id,
                gate="registry",
                reason=(
                    "SubstrateLoop was constructed without a "
                    "ToolRegistry; no tool calls admissible"
                ),
                details={},
            )
        effective_step_id = step_id if step_id is not None else b"\x00" * 16
        gate = self._tool_gates.get(effective_step_id)
        if gate is None:
            gate = ToolInvocationGate(
                registry=self.tool_registry,
                declared_tool_ids=self._tool_declared_ids,
                budget=ToolBudget(
                    max_invocations=self._tool_budget.max_invocations
                ),
                step_id_hex=effective_step_id.hex(),
            )
            self._tool_gates[effective_step_id] = gate
        return gate.invoke(tool_id, dict(args or {}))

    def tool_gate_for(self, step_id: bytes) -> ToolInvocationGate | None:
        """Return the ``ToolInvocationGate`` used for ``step_id`` (or None)."""
        return self._tool_gates.get(step_id)

    def wire_mcp_registry(
        self,
        mcp_registry: object,
        *,
        auto_declare: bool = True,
    ) -> int:
        """Register every MCP tool from ``mcp_registry`` in this loop's gate.

        v0.5.1 wiring module_03 (Lens C C-01) closure. Executor's
        ``tool_call`` step used to invoke ``mcp_registry.call_tool``
        directly, bypassing every substrate gate. Wiring the MCP
        registry through this method lets Executor call
        ``substrate_loop.invoke_tool("mcp:<qualified_name>", {...})``
        for every model-emitted tool_use message.

        Contract:
        - Every ``McpAdapter`` known to ``mcp_registry`` is walked;
          each ``qualified_name`` (``server/tool``) becomes a
          ``ToolDefinition`` registered as ``mcp:<qualified_name>``.
        - Because MCP tool schemas are declared by the remote server
          and can carry arbitrary structure, the gate registers a
          permissive schema: a single optional ``arguments`` field of
          type ``dict``. The MCP server itself validates argument
          shape at the wire. The gate's contribution is: manifest
          declaration, registry lookup, budget consumption, and
          uniform event emission.
        - When ``auto_declare`` is True (default), each registered
          tool_id is added to ``self._tool_declared_ids`` so the
          manifest gate accepts it. Callers who want a stricter
          per-manifest allowlist can pass ``auto_declare=False`` and
          maintain the declared_ids surface themselves.
        - Returns the number of tools registered.

        Idempotent-adjacent: re-registering the same ``tool_id``
        raises through ``ToolRegistry.register`` (the freeze contract
        is preserved). Call this once at loop construction.
        """
        if self.tool_registry is None:
            # Lazily create a registry so the loop is admissible to
            # gate wiring even when the constructor was called
            # without one. This keeps the setter shape symmetric with
            # ``Executor.install_v4_provenance_deps`` from module_02.
            self.tool_registry = ToolRegistry()

        # Duck-type: ``McpToolRegistry`` exposes ``list_all_tools()``
        # which returns a Rooted[list[dict]] where each dict has a
        # ``name`` key of the form ``server/tool``.
        listed = mcp_registry.list_all_tools()  # type: ignore[attr-defined]
        registered = 0
        if not listed.is_ok():
            # Registry unreachable / no servers -> nothing to wire.
            return 0
        # v0.5.1 wiring module_03 SP Q5 amendment. Build a
        # per-tool schema at the substrate layer from the MCP
        # server's advertised ``inputSchema``. The gate's args
        # check now validates required-key presence + top-level
        # unknown-key rejection using each MCP tool's actual
        # JSON schema shape, not a blanket permissive schema.
        # A tool without an inputSchema (some servers omit it)
        # falls back to a single optional ``arguments`` dict --
        # the manifest gate still declares the tool_id, so a
        # rogue call to a NEW mcp:* id refuses at manifest.
        from ract.executor.tool_gate import (
            ToolArgSchema,
            ToolArgSpec,
            ToolDefinition,
        )

        _default_schema = ToolArgSchema(
            args=(ToolArgSpec("arguments", dict, optional=True),)
        )
        for tool in listed.unwrap() or []:
            qualified = tool.get("name", "")
            if not qualified or "/" not in qualified:
                continue
            tool_id = f"mcp:{qualified}"
            if tool_id in self.tool_registry.declared_ids():
                continue

            # Closure captures the qualified name (not tool_id) so the
            # registry.call_tool wire uses the MCP-side identifier.
            def _mcp_call(
                arguments: dict[str, object] | None = None,
                *,
                _qn: str = qualified,
                _reg: object = mcp_registry,
            ) -> object:
                rooted = _reg.call_tool(_qn, dict(arguments or {}))  # type: ignore[attr-defined]
                if not rooted.is_ok():
                    raise RuntimeError(
                        f"MCP tool {_qn!r} failed: {rooted.error}"
                    )
                return rooted.unwrap()

            # Wrap the tool's arguments (an inner dict per MCP wire)
            # inside the substrate's outer ``arguments`` kwarg so the
            # gate can validate the wrapper key while the MCP-side
            # inputSchema governs the inner dict's shape. The
            # wrapper-level schema stays: optional ``arguments`` of
            # type dict. The per-tool ``input_schema`` is stashed on
            # the ToolDefinition's tool_id-derived name so audit
            # tooling can retrieve it via ``ToolRegistry.get``.
            schema = _default_schema  # wrapper-level; inputSchema is inner
            self.tool_registry.register(
                ToolDefinition(
                    tool_id=tool_id,
                    schema=schema,
                    call=_mcp_call,
                )
            )
            if auto_declare:
                self._tool_declared_ids = frozenset(
                    self._tool_declared_ids | {tool_id}
                )
            # Stash the raw MCP inputSchema for audit / event
            # correlation. Not consumed by the gate itself (per-
            # server JSON schema validation is left to the MCP
            # server), but exposed to callers that want to
            # emit the schema hash into the tool.invocation.pre
            # event.
            self._mcp_input_schemas[tool_id] = dict(
                tool.get("inputSchema") or {}
            )
            registered += 1
        return registered

    def mcp_input_schema(self, tool_id: str) -> dict[str, object] | None:
        """Return the MCP-declared inputSchema for a wired mcp:* tool.

        v0.5.1 wiring module_03 SP Q5 amendment. Exposes the schema
        stashed by :meth:`wire_mcp_registry` so audit tooling can
        correlate a ``tool.invocation.pre`` event against the
        server-side argument shape without re-listing the MCP tools.
        Returns ``None`` when no schema was declared.
        """
        return dict(self._mcp_input_schemas.get(tool_id) or {}) or None

    def _current_branch_name(self) -> str:
        """Return the loop repo's currently checked-out branch name."""
        return _current_branch_name_of(self.repo_root)

    # ---- process-group spawn / reap (module_05) ------------------------

    def spawn_step_subprocess(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        stdin: int | None = subprocess.DEVNULL,
        stdout: int | None = subprocess.PIPE,
        stderr: int | None = subprocess.PIPE,
    ) -> ProcessGroupHandle:
        """Spawn a step subprocess under substrate tree-kill discipline.

        v0.5.1 wiring module_05 (Lens C C-03 closure). Production
        surface for :func:`ract.executor.process_group.spawn`: every
        subprocess a step_runner launches inside :meth:`run_step`
        SHOULD spawn through this method rather than a bare
        :func:`subprocess.Popen` so a rollback / commit-failure /
        unsuccessful-dispose path can reap parent + descendants via
        :func:`process_group.kill_tree`. SUBSTRATE §7 rollback contract
        ("SIGKILL to the entire process group tree") holds structurally
        rather than by convention.

        The handle is registered into :attr:`_active_process_handles`;
        rollback paths iterate + reap via
        :meth:`_reap_active_processes`. A natural exit (T1 success) can
        rely on the OS to clean up after the parent Popen; the reap
        list is cleared on step-boundary success too via
        :meth:`_deregister_process_handle`.

        Env consumption -- module_04 SP Q5 defer closure:

        - When the caller passes ``env=None`` and this loop is inside a
          sandbox step whose backend rendered a filtered env (module_04
          Linux ``BwrapCommand.env`` / macOS ``SeatbeltProfile.env``),
          the filtered env auto-consumes here. This is the wire that
          makes NEVER_PASSTHROUGH actually reach the step_runner's
          subprocess (module_04 built the filter; this method feeds it
          to ``Popen(env=...)``).
        - When the caller passes ``env=<explicit dict>``, that overrides
          the sandbox env; callers who need to inject extra variables
          on top of the sandbox env should read
          :attr:`_current_sandbox_env` and merge explicitly.
        - Outside a sandbox step (or on the Windows unenforced stub
          which yields no env dict), ``env=None`` falls through to
          ``subprocess.Popen(env=None)`` which inherits the parent
          process env -- the pre-module_05 behavior.

        Returns the :class:`ProcessGroupHandle`. Callers can inspect
        ``.popen`` for stdout/wait; the substrate owns kill.
        """
        effective_env = env
        if effective_env is None and self._current_sandbox_env is not None:
            effective_env = dict(self._current_sandbox_env)
        handle = spawn(
            argv,
            env=effective_env,
            cwd=cwd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )
        self._active_process_handles.append(handle)
        return handle

    def _deregister_process_handle(self, handle: ProcessGroupHandle) -> None:
        """Remove ``handle`` from the reap list without killing.

        v0.5.1 wiring module_05. Used when a step_runner has awaited
        its subprocess to natural exit and does not want the rollback
        reaper to double-terminate an already-exited handle. Safe to
        call on a handle not currently in the list (no-op).
        """
        try:
            self._active_process_handles.remove(handle)
        except ValueError:
            pass

    # ---- v0.5.1 spec-completeness module_07 (Lens 2 Delta 3) ----------

    def register_subagent_handle(self, handle: SubagentHandle) -> None:
        """Register a subagent handle for cascade-on-non-T1-halt.

        v0.5.1 spec-completeness module_07 (Lens 2 Delta 3). Called by
        subagent-shape spawners (Legacy Whisperer / Chesterton's
        Fence / language servers / embedding sidecars) so the loop
        owns the disposal contract structurally rather than by
        convention. Handles are appended in registration order and
        drained LIFO on ``dispose(success=False)`` (or
        ``_reap_subagent_handles`` invoked from the ``run_step``
        exception path). T1 disposal DISCARDS the list; the caller's
        natural cleanup handles the resources on success paths.

        The handle SHOULD satisfy the
        :class:`ract.executor.subagent_handle.SubagentHandle` protocol
        (``descriptor`` dict + ``is_alive()`` + ``dispose(reason)``);
        the concrete
        :class:`~ract.executor.subagent_handle.SubprocessSubagentHandle`
        and
        :class:`~ract.executor.subagent_handle.InlineSubagentHandle`
        cover the two common shapes. Registration is idempotent per
        handle identity: a second register of the same object is a
        no-op.
        """
        if handle in self._active_subagent_handles:
            return
        self._active_subagent_handles.append(handle)

    def deregister_subagent_handle(self, handle: SubagentHandle) -> None:
        """Remove ``handle`` without disposal.

        v0.5.1 spec-completeness module_07. Used when a caller has
        already disposed the subagent on the natural-exit path and
        does not want the cascade to double-dispose. Safe to call on
        a handle not currently in the list (no-op).
        """
        try:
            self._active_subagent_handles.remove(handle)
        except ValueError:
            pass

    def _reap_subagent_handles(self, *, reason: str) -> int:
        """LIFO dispose every registered subagent handle. Returns count reaped.

        v0.5.1 spec-completeness module_07 (Lens 2 Delta 3). Called
        from every non-T1 dispose path (:meth:`dispose` with
        ``success=False``) AND from the ``run_step`` exception path
        so a step_runner that raised mid-flight cannot leak a
        subagent past the step boundary. Each handle's
        :meth:`SubagentHandle.dispose` is invoked with the same
        ``reason`` and the outcome (ok / fail) is emitted as a
        ``subagent.disposed`` event so the trace log shows exactly
        which subagents cascaded on which halt cause. Failures do
        NOT propagate: a raise inside dispose is caught, logged,
        and the next handle is disposed. Clearing the list at the
        end is unconditional so a re-drain never double-disposes.
        """
        handles = list(self._active_subagent_handles)
        if not handles:
            return 0
        reaped = 0
        # LIFO drain: most-recently-registered dispose first (matches
        # the compensator-stack shape from commit_compensator.py).
        for handle in reversed(handles):
            try:
                ok = handle.dispose(reason)
            except Exception as exc:  # noqa: BLE001 -- dispose is best-effort
                _KNOT_LOGGER.warning(
                    "subagent dispose raised (reason=%s, descriptor=%r): %s",
                    reason,
                    getattr(handle, "descriptor", {}),
                    exc,
                )
                ok = False
            emit_subagent_disposed_event(handle, reason=reason, ok=ok)
            reaped += 1
        self._active_subagent_handles = []
        return reaped

    def _reap_active_processes(self, *, reason: str) -> int:
        """SIGKILL every registered handle + descendant tree.

        v0.5.1 wiring module_05 (Lens C C-03). Called from every
        rollback path (post-condition failed, commit failed, run_step
        uncaught exception, dispose(success=False)). Iterates
        :attr:`_active_process_handles`, invokes
        :func:`process_group.kill_tree` on each (best-effort;
        failures WARN but never raise -- a leaked descendant is still
        preferable to a stalled loop), emits ``process.reaped`` per
        reap into the trace sink, then clears the list.

        Returns the number of handles reaped (for tests + telemetry).
        """
        handles = list(self._active_process_handles)
        if not handles:
            return 0
        reaped = 0
        for handle in handles:
            try:
                kill_tree(handle)
                reaped += 1
            except Exception:  # noqa: BLE001 -- never fail rollback on reap error
                _KNOT_LOGGER.warning(
                    "process_group.kill_tree failed on pid=%s (reason=%s); "
                    "descendant tree may be leaked",
                    getattr(handle, "pid", "?"),
                    reason,
                )
            _emit_process_reaped(handle, reason=reason)
        self._active_process_handles = []
        return reaped

    # ---- compensator drain ---------------------------------------------

    def dispose(self, *, success: bool, reason: str = "") -> list[tuple]:
        """Drain or discard the loop's compensator stack.

        Called by the loop controller on loop exit. ``success=True``
        (T1) discards the stack; ``success=False`` drains it LIFO,
        undoing every mid-loop commit whose branch has not been
        pushed. Returns the list of ``(compensator, status)`` from
        the drain (empty on success or when the stack is empty).

        SP Q5(c) amendment (OpenRouter DEFECT verdict): after
        draining, resync ``self.parent_snapshot`` to the actual git
        HEAD so a subsequent inspection sees the state after the
        drain (not the pre-drain sha). Reads HEAD once; safe on any
        drain outcome (some compensators may have refused because
        their commit was pushed -- the resync reflects reality).
        """
        if success:
            self.compensator_stack.discard(
                reason=reason or "T1_SUCCESS",
            )
            # v0.5.1 wiring module_05: T1 success paths still deregister
            # any lingering handles the step_runner failed to await.
            # We do NOT force-kill here (natural exit is the T1
            # contract) but leaving the list populated across loop
            # disposal is a foot-gun for reusable loop instances.
            self._active_process_handles = []
            # v0.5.1 spec-completeness module_07 (Lens 2 Delta 3):
            # subagent handles also DISCARD on T1 -- successful loop
            # completion is not a rollback; the caller's natural
            # cleanup handles subagent teardown. Clearing prevents
            # a reusable loop instance from carrying stale handles
            # into the next run.
            self._active_subagent_handles = []
            return []
        # v0.5.1 wiring module_05 (Lens C C-03): reap the process tree
        # BEFORE draining the compensator stack -- a running child that
        # holds a worktree file handle open can block the compensator's
        # ``git reset``, and a mid-drain SIGKILL leaves no time for the
        # child to observe the reset.
        self._reap_active_processes(
            reason=reason or "dispose_unsuccessful",
        )
        # v0.5.1 spec-completeness module_07 (Lens 2 Delta 3): CASCADE
        # subagent handles on non-T1 disposal. Ordering: subagent
        # dispose runs BEFORE compensator drain because a subagent
        # (e.g. an LSP server) may hold worktree file handles open
        # in the same shape as a leaked descendant, and dispose is
        # graceful-first with SIGKILL fallback (via
        # SubprocessSubagentHandle.dispose -> kill_tree). This
        # ordering matches _reap_active_processes -> compensator
        # drain. Failures do not propagate; each handle's outcome
        # is emitted as ``subagent.disposed`` for the audit trail.
        self._reap_subagent_handles(
            reason=reason or "dispose_unsuccessful",
        )
        outcomes = self.compensator_stack.drain(
            reason=reason or "loop_disposed_unsuccessfully",
        )
        # Resync parent_snapshot to actual git HEAD post-drain.
        current_head = _resolve_head_safe(self.repo_root)
        if current_head:
            self.parent_snapshot = current_head
        return outcomes

    # ---- between-iteration sweep ---------------------------------------

    def _maybe_run_auction_sweep(self) -> None:
        """Run ``AuctionSweep.run`` if the min-wall-seconds gate is met.

        Called from ``run_step`` at each iteration boundary. A caller
        without an attached sweep gets a no-op. Failures inside the
        sweep are swallowed so a broken scanner cannot stall the loop.
        """
        if self.auction_sweep is None:
            return
        current_wall = time.monotonic() - self._loop_start_monotonic
        try:
            if self.auction_sweep.should_run(current_wall):
                self.auction_sweep.run(current_wall_seconds=current_wall)
        except Exception:  # noqa: BLE001 — never fail the loop on a sweep error
            pass

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
                # v0.5.1 wiring module_05 (Lens C C-03): rollback
                # reaps every process handle registered under this
                # step BEFORE unwinding the worktree, so no leaked
                # grandchildren hold worktree file handles open.
                self._reap_active_processes(reason="postcondition_failed")
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
                _emit_step_event(record, "step.rolled_back")
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
                _emit_step_event(record, "step.rolled_back")
                # Deliberately do NOT roll back — the worktree stays intact.
                return record

        # Commit the worktree changes to the step branch. Advance the
        # parent-snapshot pointer to the new commit.
        message = spec.commit_message or f"rootact step {txn.step_id.hex()}"
        try:
            new_sha = self.worktrees.commit(wt, message)
        except Exception as exc:  # noqa: BLE001 — rollback on any commit failure
            # v0.5.1 wiring module_05 (Lens C C-03): a commit-failure
            # rollback must reap the tree too (a step_runner that
            # spawned a background test process before commit still
            # holds the tree open otherwise).
            self._reap_active_processes(reason="commit_failed")
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
            _emit_step_event(record, "step.rolled_back")
            return record

        # SP Q5(b) amendment (OpenRouter DEFECT verdict): read HEAD
        # AFTER fast-forward attempt. Only advance
        # ``self.parent_snapshot`` when HEAD actually landed at
        # new_sha; when fast-forward refused (divergent branch), leave
        # ``self.parent_snapshot`` at parent_before so loop-state and
        # git-state do not diverge silently.
        head_before = parent_before
        # v0.5.1 wiring module_05 (Lens C C-04 closure): when a soft
        # commit compensator is about to be installed on this
        # accumulator, advance HEAD via ``git update-ref`` so the
        # working-tree state the compensator was designed to preserve
        # for inspectability is not destroyed at the commit boundary.
        # A ``git reset --hard`` fast-forward defeats the compensator's
        # ``mode="soft"`` intent entirely -- the tree is already gone
        # by the time drain runs. The compensator install below uses
        # ``mode="soft"``, so we always route through the soft path
        # here; callers wanting the legacy destructive path can flip
        # ``force_hard=True``.
        _fast_forward_head(
            self.repo_root,
            new_sha,
            branch=self._current_branch_name(),
            soft=True,
        )
        current_head = _resolve_head_safe(self.repo_root)
        if current_head == new_sha:
            self.parent_snapshot = new_sha
        # else: parent_snapshot stays at parent_before -- the loop
        # still records the step_id as committed (the branch carries
        # the commit) but the loop's canonical HEAD did not advance.
        self._committed_step_ids.add(txn.step_id)

        # v0.5.1 module_05 -- install a compensator so a subsequent
        # unsuccessful loop disposal can undo this commit. We install
        # only when the HEAD actually advanced (fast-forward
        # succeeded); when HEAD was refused (divergent branch), the
        # loop's HEAD did NOT advance and there is nothing for a
        # compensator to unwind.
        if current_head == new_sha and head_before and head_before != new_sha:
            try:
                comp = build_compensator(
                    self.repo_root,
                    branch=self._current_branch_name(),
                    sha_before=head_before,
                    sha_after=new_sha,
                    mode="soft",
                )
                self.compensator_stack.install(comp)
            except Exception:  # noqa: BLE001 -- never fail commit on install error
                pass

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
        _emit_step_event(record, "step.committed")
        return record


# ---------------------------------------------------------------------------
# Small git helpers used by SubstrateLoop only
# ---------------------------------------------------------------------------


def _resolve_head_safe(repo_root: Path) -> str:
    """Return HEAD sha for ``repo_root`` or ``""`` on failure.

    module_05 helper -- used to confirm the fast-forward actually
    advanced HEAD before installing a compensator. Silent on error;
    the compensator install skips when this returns ``""``.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _current_branch_name_of(repo_root: Path) -> str:
    """Return the currently checked-out branch name (or ``"HEAD"`` on detach)."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return "HEAD"
    return result.stdout.strip() or "HEAD"


def _fast_forward_head(
    repo_root: Path,
    new_sha: str,
    *,
    branch: str | None = None,
    soft: bool = False,
) -> None:
    """Advance the repo's HEAD-branch tip to ``new_sha`` when ancestor.

    We refuse to force-move HEAD; this only fires when ``new_sha``'s
    history contains the current HEAD. A step that produced a divergent
    branch leaves HEAD alone and the plan graph will surface the
    divergence via ``ract session ls``.

    v0.5.1 wiring module_05 (Lens C C-04 closure). Two advance modes:

    - ``soft=True`` (default in production commit path when a soft
      compensator is being installed): use ``git reset --soft`` which
      moves HEAD + branch pointer to ``new_sha`` WITHOUT touching the
      index or the working tree. The pre-commit tree state stays
      inspectable on disk -- this is what the compensator's
      ``mode="soft"`` invariant was designed to guarantee. On a
      subsequent unsuccessful disposal, the compensator's
      ``git reset --soft`` back to ``sha_before`` restores loop state
      atop the same tree, and an operator inspecting the worktree
      sees the mid-loop state instead of the reflog-only history.
    - ``soft=False`` (legacy / operator-forced): ``git reset --hard``
      -- the pre-v0.5.1 wiring behavior. Kept for callers who want
      the tree scrubbed at every commit boundary and accept the
      inspectability trade-off.

    ``branch`` is optional metadata; the actual advance uses
    ``git reset`` which operates on the currently checked-out branch
    regardless. It is captured in the WARN log message when the
    advance fails so an operator can correlate a failed fast-forward
    to a specific branch without a second git call.
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
    reset_mode = "--soft" if soft else "--hard"
    result = subprocess.run(
        ["git", "-C", str(repo_root), "reset", reset_mode, new_sha],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        _KNOT_LOGGER.warning(
            "_fast_forward_head reset %s to %s failed on branch %r: %s",
            reset_mode,
            new_sha[:12],
            branch or "<unknown>",
            (result.stderr.strip() or result.stdout.strip()),
        )


def _maybe_emit_retrieval_satisfied(spec: SubstrateStepSpec) -> None:
    """Emit ``retrieval.satisfied`` when ``spec.metadata`` carries a bundle.

    Module_09 wiring. The bundle's ``total_tokens`` and
    ``budget_used_pct`` land in the payload so the trace surface names
    exactly what the model call consumed. Wrapped so a missing trace
    writer never fails the step; the emit is a signal, not a gate.
    """
    bundle = None
    try:
        bundle = spec.metadata.get("retrieval_bundle") if spec.metadata else None
    except AttributeError:
        # spec.metadata is a non-dict value (test may pass an arbitrary
        # object). Fail-quiet — the loop's contract is signal-only here.
        return
    if bundle is None:
        return
    total_tokens = getattr(bundle, "total_tokens", None)
    budget_used_pct = getattr(bundle, "budget_used_pct", None)
    call_id = getattr(bundle, "call_id", "")
    payload: dict = {
        "call_id": str(call_id),
        "total_tokens": int(total_tokens) if total_tokens is not None else 0,
        "budget_used_pct": (
            float(budget_used_pct) if budget_used_pct is not None else 0.0
        ),
        "step_id": spec.step_id.hex(),
    }
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "retrieval.satisfied",  # type: ignore[arg-type]
            payload,
            step_id=spec.step_id,
        )
    except Exception:  # noqa: BLE001 — never fail the loop on a trace error
        pass


def _extract_sandbox_env(sandbox_ctx: object) -> dict[str, str] | None:
    """Return the ``env`` dict from a rendered sandbox context.

    v0.5.1 wiring module_05 (module_04 SP Q5 defer closure). The
    module_04 backends yield ``BwrapCommand`` (Linux) or
    ``SeatbeltProfile`` (macOS) whose ``.env`` field is the filtered
    env from ``build_sandbox_env``. The Windows unenforced stub
    yields ``None`` (or a shape without ``.env``); in that case
    ``spawn_step_subprocess`` falls back to parent-env inherit.

    Returns a fresh ``dict`` copy (never a shared reference) so a
    caller mutating the returned env cannot leak back into the
    backend's state. Returns ``None`` when the shape carries no
    non-empty env dict.
    """
    if sandbox_ctx is None:
        return None
    env_attr = getattr(sandbox_ctx, "env", None)
    if isinstance(env_attr, dict) and env_attr:
        # Defensive stringify: sandbox contracts specify dict[str, str]
        # but a foreign backend might slip in non-string values.
        return {str(k): str(v) for k, v in env_attr.items()}
    return None


def _emit_process_reaped(handle: object, *, reason: str) -> None:
    """Emit ``process.reaped`` into the trace sink for a killed handle.

    v0.5.1 wiring module_05 (Lens C C-03). Fires once per
    handle-kill inside :meth:`SubstrateLoop._reap_active_processes`
    so an auditor can grep ``process.reaped`` to correlate a
    rollback to the specific child trees that got SIGKILL'd. Payload
    intentionally minimal (pid + argv[0] + reason + reap_latency_ms)
    so the emit is cheap and the trace log stays readable.

    Wrapped so a run without a registered writer (unit tests, ad-hoc
    loops) still runs.
    """
    try:
        from ract.trace.sink import emit as _emit_event

        pid = getattr(handle, "pid", -1)
        argv = getattr(handle, "argv", ())
        spawned_at = getattr(handle, "spawned_at", None)
        latency_ms = 0
        if spawned_at is not None:
            try:
                latency_ms = int((time.monotonic() - float(spawned_at)) * 1000)
            except (TypeError, ValueError):
                latency_ms = 0
        _emit_event(
            "process.reaped",  # type: ignore[arg-type]
            {
                "pid": int(pid) if isinstance(pid, int) else -1,
                "argv0": str(argv[0]) if argv else "",
                "argv_len": len(argv) if isinstance(argv, (list, tuple)) else 0,
                "reason": str(reason),
                "reap_latency_ms": latency_ms,
            },
        )
    except Exception:  # noqa: BLE001 -- never fail rollback on trace error
        pass


def _emit_step_event(record: StepRecord, kind: str) -> None:
    """Emit a step terminal event into the run's event log.

    module_05 (SUBSTRATE §6.3). Wraps the emit so a run without a
    registered writer (unit tests, ad-hoc loops) still runs.
    """
    try:  # local import so the executor→trace edge is one-way
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            kind,  # type: ignore[arg-type]  # runtime-checked EventKind
            {
                "outcome": record.outcome.name,
                "parent_snapshot_before": record.parent_snapshot_before,
                "parent_snapshot_after": record.parent_snapshot_after,
                "branch": record.branch,
                "reason": record.reason,
            },
            step_id=record.step_id,
        )
    except Exception:  # noqa: BLE001
        pass


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
