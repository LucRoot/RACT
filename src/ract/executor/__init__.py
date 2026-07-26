"""RACT executor package.

The historical ``ract.executor`` was a single module carrying the
provider-facing step executor (``Executor``, ``ExecutionReport``,
``StepResult``). v0.4 (SUBSTRATE §3) turns it into a package so the
transactional substrate primitives — worktree-per-step
(``worktree.py``), optional container-per-step (``runtime.py``), and
the loop that schedules them (``loop.py``) — can live alongside the
provider executor without either surface bloating the other.

Historical imports remain source-compatible: ``from ract.executor import
Executor, ExecutionReport, StepResult`` still resolves. The classes now
live in ``ract.executor.steps`` and are re-exported here.

Module_03 will land the OS-enforced sandbox on top of the container
shim in ``runtime.py``.
"""

from ract.executor.runtime import (
    ContainerBackend,
    DaggerBackend,
    PodmanBackend,
    RuntimeError as ContainerRuntimeError,
)
from ract.executor.steps import ExecutionReport, Executor, StepResult
from ract.executor.worktree import (
    Worktree,
    WorktreeError,
    WorktreeManager,
    ensure_clean_tracked_tree,
    ensure_git_repo,
    resolve_head_sha,
)

# ``ract.executor.loop`` (SubstrateLoop, SubstrateStepSpec, StepRecord) is
# NOT re-exported from this ``__init__`` because loop.py transitively
# imports ``ract.core.loop`` → ``ract.loop_planner`` → ``ract.harness``,
# and ``harness`` itself imports from ``ract.executor``. Re-exporting at
# package init would trigger that cycle. Callers import
# ``ract.executor.loop`` explicitly (see ``tests/property/
# test_transaction_atomicity.py``); the module is kept alive against the
# dead-code auction via the allowlist entry ``loop.py`` (module_02).

__all__ = [
    "ContainerBackend",
    "ContainerRuntimeError",
    "DaggerBackend",
    "ExecutionReport",
    "Executor",
    "PodmanBackend",
    "StepResult",
    "Worktree",
    "WorktreeError",
    "WorktreeManager",
    "ensure_clean_tracked_tree",
    "ensure_git_repo",
    "resolve_head_sha",
]

# Concrete reference so static reachability tooling sees the dependency
# (module_01 landed the same pattern in ``ract.core.__init__`` after the
# dead-code auction flagged compile.py / gates.py).
_EXECUTOR_EXPORTS = (
    ContainerBackend,
    DaggerBackend,
    PodmanBackend,
    ContainerRuntimeError,
    ExecutionReport,
    Executor,
    StepResult,
    Worktree,
    WorktreeError,
    WorktreeManager,
    ensure_clean_tracked_tree,
    ensure_git_repo,
    resolve_head_sha,
)

# RACT 0.4.0
