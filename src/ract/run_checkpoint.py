"""A checkpoint per run, so a killed run resumes (ADR-0049 D13, B-070).

LR:: A run saved its session record once, after the last step. A run
killed during step 2 of 3 left files on disk and no record of which steps
had finished, so nothing could be resumed (B-066). Each run now keeps one
file, rewritten when a step starts (before it touches any file), when it
saves a file it is about to replace or create, when it has written that
file, and when the step finishes. Every write is atomic: a temporary file
in the same folder, flushed, then replaced over the old one.

The file lives in the user state directory, keyed by the repository like
the undo store, so a cloned repository cannot ship one. It is still read
as untrusted data: the run id is a name, a link is not read, the size is
capped, the schema is closed, the root must be this repository's, and the
stored plan must match its `plan_hash` (D12).

Finished means the harness recorded `done` for the step, never the
model's word. On the worktree path a step is finished only once its
changes reached the user's files, so the executor's own finish inside the
step's worktree is deferred (``finish_deferred``).

Resetting the interrupted step restores the bytes that step replaced and
removes what it created. The bytes come from a copy taken when the step
saved the file, so a file an earlier, finished step also changed gets that
step's version back. A file that changed after the step wrote it, or that
the step saved and may not have written, is left as it is and named.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ract import undo_backup
from ract.canonical import dumps_jcs
from ract.manager import Plan, Step

SCHEMA = "ract.checkpoint/1"
MAX_CHECKPOINT_BYTES = 256 * 1024
# Inside a turn's backup folder; no workspace path can be under `.ract`.
_STEP_COPIES = (".ract", "steps")

_TOP_KEYS = {
    "schema",
    "root",
    "run",
    "intent",
    "plan",
    "plan_hash",
    "finished",
    "in_progress",
}
_PLAN_KEYS = {"assumption", "confidence", "steps"}
_STEP_KEYS = {"n", "action", "target", "provider_hint", "tool_call"}
_PROGRESS_KEYS = {"n", "backup_id", "worktree", "files"}
# B-097: how a step that did not finish ended, when it was not interrupted.
# Optional, so a checkpoint written before it is still read.
_ENDED = frozenset({"refused", "failed"})
_FILE_KEYS = {"path", "before", "after", "written"}
_HEX = set("0123456789abcdef")


class CheckpointRefused(ValueError):
    """A checkpoint that is not trusted; the message says why."""


def runs_dir(root: Path | str) -> Path:
    """This repository's run checkpoints, in the user state directory."""
    from ract.core.keys import _default_state_dir

    key = undo_backup.repository_key(root)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return _default_state_dir() / "runs" / digest


def checkpoint_path(root: Path | str, run_id: object) -> Path:
    """The checkpoint file for *run_id*; ValueError when the id is not a name."""
    name = undo_backup.require_name(run_id, "run id")
    return runs_dir(root) / f"{name}.json"


def new_run_id() -> str:
    """A run id for a one-shot run without ``--session``."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{stamp}-{uuid.uuid4().hex[:6]}"


def plan_hash(plan: Plan) -> str:
    """D12: sha256 of the canonical JSON of the steps' n, action and target."""
    steps = [
        {"n": n, "action": step.action, "target": step.expected_artifact or None}
        for n, step in enumerate(plan.steps, start=1)
    ]
    return hashlib.sha256(dumps_jcs(steps)).hexdigest()


def _plan_data(plan: Plan) -> dict[str, Any]:
    return {
        "assumption": plan.assumption,
        "confidence": float(plan.confidence),
        "steps": [
            {
                "n": n,
                "action": step.action,
                "target": step.expected_artifact or None,
                "provider_hint": step.provider_hint,
                "tool_call": step.tool_call,
            }
            for n, step in enumerate(plan.steps, start=1)
        ],
    }


def stored_plan(state: dict[str, Any]) -> Plan:
    """The plan a loaded checkpoint holds."""
    plan = state["plan"]
    return Plan(
        assumption=plan["assumption"],
        confidence=plan["confidence"],
        steps=[
            Step(
                action=step["action"],
                provider_hint=step["provider_hint"],
                expected_artifact=step["target"] or "",
                tool_call=step["tool_call"],
            )
            for step in plan["steps"]
        ],
    )


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


# ------------------------------------------------------------------ reading


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _check_keys(value: object, keys: set[str], what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CheckpointRefused(f"{what} is not an object")
    if set(value) != keys:
        extra = sorted(set(value) - keys)
        missing = sorted(keys - set(value))
        raise CheckpointRefused(
            f"{what} has unknown keys {extra} or lacks keys {missing}"
        )
    return value


def _check_schema(data: object, root: Path, run_id: str) -> dict[str, Any]:
    top = _check_keys(data, _TOP_KEYS, "the checkpoint")
    if top["schema"] != SCHEMA:
        raise CheckpointRefused(f"schema {top['schema']!r} is not {SCHEMA}")
    if top["root"] != undo_backup.repository_key(root):
        raise CheckpointRefused("it was written for another repository")
    if top["run"] != run_id:
        raise CheckpointRefused("it was written for another run")
    if not isinstance(top["intent"], str):
        raise CheckpointRefused("intent is not text")
    plan = _check_keys(top["plan"], _PLAN_KEYS, "the plan")
    if not isinstance(plan["assumption"], str):
        raise CheckpointRefused("the plan's assumption is not text")
    if not isinstance(plan["confidence"], (int, float)) or isinstance(
        plan["confidence"], bool
    ):
        raise CheckpointRefused("the plan's confidence is not a number")
    steps = plan["steps"]
    if not isinstance(steps, list) or not steps:
        raise CheckpointRefused("the plan has no steps")
    for n, raw in enumerate(steps, start=1):
        step = _check_keys(raw, _STEP_KEYS, f"step {n}")
        if not _is_int(step["n"]) or step["n"] != n:
            raise CheckpointRefused(f"step {n} is numbered {step['n']!r}")
        if not isinstance(step["action"], str) or not isinstance(
            step["provider_hint"], str
        ):
            raise CheckpointRefused(f"step {n}'s action or provider is not text")
        if step["target"] is not None and not isinstance(step["target"], str):
            raise CheckpointRefused(f"step {n}'s target is not text")
        if step["tool_call"] is not None and not isinstance(step["tool_call"], dict):
            raise CheckpointRefused(f"step {n}'s tool call is not an object")
    if not _is_hash(top["plan_hash"]):
        raise CheckpointRefused("plan_hash is not a sha256")
    finished = top["finished"]
    if (
        not isinstance(finished, list)
        or not all(_is_int(n) and 1 <= n <= len(steps) for n in finished)
        or len(set(finished)) != len(finished)
    ):
        raise CheckpointRefused("finished is not a list of distinct step numbers")
    progress = top["in_progress"]
    if progress is not None:
        keys = (
            (_PROGRESS_KEYS | {"ended"})
            if isinstance(progress, dict) and "ended" in progress
            else _PROGRESS_KEYS
        )
        progress = _check_keys(progress, keys, "in_progress")
        if "ended" in progress and progress["ended"] not in _ENDED:
            raise CheckpointRefused("in_progress ended is not refused or failed")
        n = progress["n"]
        if not _is_int(n) or not 1 <= n <= len(steps) or n in finished:
            raise CheckpointRefused(
                "in_progress names a step that cannot be in progress"
            )
        if progress["backup_id"] is not None:
            try:
                undo_backup.require_name(progress["backup_id"], "backup id")
            except ValueError as exc:
                raise CheckpointRefused(str(exc)) from None
        worktree = progress["worktree"]
        if worktree is not None and not (
            isinstance(worktree, str)
            and worktree
            and len(worktree) <= 128
            and set(worktree) <= _HEX
        ):
            raise CheckpointRefused(
                "in_progress names a worktree that is not a step id"
            )
        if not isinstance(progress["files"], list):
            raise CheckpointRefused("in_progress files is not a list")
        for raw in progress["files"]:
            entry = _check_keys(raw, _FILE_KEYS, "a file entry")
            if not isinstance(entry["path"], str):
                raise CheckpointRefused("a file entry's path is not text")
            for side in ("before", "after"):
                if entry[side] is not None and not _is_hash(entry[side]):
                    raise CheckpointRefused(f"a file entry's {side} is not a sha256")
            if not isinstance(entry["written"], bool):
                raise CheckpointRefused("a file entry's written is not true or false")
    return top


def load(root: Path | str, run_id: object) -> dict[str, Any] | None:
    """The checkpoint for *run_id*, None when there is none.

    Raises CheckpointRefused for anything that is not a checkpoint this
    repository's run wrote: a bad id, a link, an oversized, truncated or
    damaged file, a file outside the schema, or a plan that does not match
    its `plan_hash`.
    """
    base = Path(os.path.realpath(root))
    try:
        path = checkpoint_path(base, run_id)
    except ValueError as exc:
        raise CheckpointRefused(str(exc)) from None
    assert isinstance(run_id, str)
    if path.is_symlink():
        raise CheckpointRefused("the checkpoint is a link")
    if not path.exists():
        return None
    if not path.is_file():
        raise CheckpointRefused("the checkpoint is not a file")
    if path.stat().st_size > MAX_CHECKPOINT_BYTES:
        raise CheckpointRefused(
            f"the checkpoint is larger than {MAX_CHECKPOINT_BYTES} bytes"
        )
    with open(path, "rb") as fh:
        raw = fh.read(MAX_CHECKPOINT_BYTES + 1)
    if len(raw) > MAX_CHECKPOINT_BYTES:
        raise CheckpointRefused(
            f"the checkpoint is larger than {MAX_CHECKPOINT_BYTES} bytes"
        )
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise CheckpointRefused(
            "the checkpoint is not complete JSON (truncated or damaged)"
        ) from None
    state = _check_schema(data, base, run_id)
    if plan_hash(stored_plan(state)) != state["plan_hash"]:
        raise CheckpointRefused("the stored plan does not match its plan_hash")
    return state


# ------------------------------------------------------------------ writing


class RunCheckpoint:
    """The checkpoint of one run, rewritten as the run goes."""

    def __init__(
        self,
        root: Path | str,
        run_id: str,
        intent: str,
        *,
        state: dict[str, Any] | None = None,
    ) -> None:
        self.root = Path(os.path.realpath(root))
        self.run_id = undo_backup.require_name(run_id, "run id")
        self.path = checkpoint_path(self.root, run_id)
        self.intent = intent
        self.state = state
        self.broken = False

    # -- the run's plan and steps

    def plan_ready(self, plan: Plan) -> None:
        """Record the plan about to run (a resumed run keeps its record)."""
        digest = plan_hash(plan)
        if self.state is not None:
            if self.state["plan_hash"] != digest:
                # The gates ran again on resume and changed a step (an
                # existing file is now answered, not written): record the
                # plan that runs.
                self.state["plan"] = _plan_data(plan)
                self.state["plan_hash"] = digest
                self._write()
            return
        self.state = {
            "schema": SCHEMA,
            "root": undo_backup.repository_key(self.root),
            "run": self.run_id,
            "intent": self.intent,
            "plan": _plan_data(plan),
            "plan_hash": digest,
            "finished": [],
            "in_progress": None,
        }
        self._write()

    def is_finished(self, n: int) -> bool:
        return self.state is not None and n in self.state["finished"]

    def step_started(self, n: int) -> None:
        if self.state is None:
            return
        progress = self.state["in_progress"]
        if progress is not None and progress["n"] == n:
            return  # the executor starting the step the adapter started
        self.state["in_progress"] = {
            "n": n,
            "backup_id": undo_backup.current_backup_id(),
            "worktree": None,
            "files": [],
        }
        self._write()

    def note_worktree(self, step_id_hex: str) -> None:
        progress = self.state["in_progress"] if self.state is not None else None
        if progress is None:
            return
        progress["worktree"] = step_id_hex
        self._write()

    def note_saving(self, backup: undo_backup.TurnBackup, key: str, full: Path) -> None:
        """*full* is about to be replaced or created by the step in progress."""
        progress = self.state["in_progress"] if self.state is not None else None
        if progress is None or Path(os.path.realpath(backup.root)) != self.root:
            return
        if any(entry["path"] == key for entry in progress["files"]):
            return
        before = None
        if full.is_file():
            copy = backup.folder.joinpath(*_STEP_COPIES, str(progress["n"]), key)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(full, copy)
            before = _sha256(copy)
        if progress["backup_id"] is None:
            progress["backup_id"] = backup.turn_id
        progress["files"].append(
            {"path": key, "before": before, "after": None, "written": False}
        )
        self._write()

    def note_written(self, root: Path | str, paths: Iterable[Path | str]) -> None:
        progress = self.state["in_progress"] if self.state is not None else None
        if progress is None:
            return
        base = Path(os.path.realpath(root))
        changed = False
        for path in paths:
            full = Path(os.path.realpath(base / path))
            try:
                key = full.relative_to(self.root).as_posix()
            except ValueError:
                continue  # a step worktree: not the user's files
            for entry in progress["files"]:
                if entry["path"] == key:
                    entry["after"] = _sha256(full)
                    entry["written"] = True
                    changed = True
        if changed:
            self._write()

    def step_ended(self, n: int, outcome: str) -> None:
        """Step *n* ended without finishing: refused or failed (B-097)."""
        progress = self.state["in_progress"] if self.state is not None else None
        if progress is None or progress["n"] != n or outcome not in _ENDED:
            return
        progress["ended"] = outcome
        self._write()

    def step_finished(self, n: int) -> None:
        if self.state is None:
            return
        if n not in self.state["finished"]:
            self.state["finished"] = sorted([*self.state["finished"], n])
        progress = self.state["in_progress"]
        if progress is not None and progress["n"] == n:
            self.state["in_progress"] = None
        self._write()

    def unfinished(self) -> bool:
        if self.state is None:
            return False
        return len(self.state["finished"]) < len(self.state["plan"]["steps"])

    def complete(self) -> None:
        """Remove the checkpoint once every step finished."""
        if self.state is None or self.unfinished() or self.state["in_progress"]:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            return

    # -- the file

    def _write(self) -> None:
        if self.broken or self.state is None:
            return
        folder = self.path.parent
        tmp = folder / f".{self.run_id}.{uuid.uuid4().hex[:8]}.tmp"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            data = json.dumps(self.state, indent=1).encode("utf-8")
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except OSError as exc:
            # A checkpoint that cannot be kept current must not be trusted
            # later: remove it and say once that this run cannot resume.
            self.broken = True
            print(
                f"note: this run's checkpoint could not be written ({exc}); "
                "it cannot be resumed",
                flush=True,
            )
            for leftover in (tmp, self.path):
                try:
                    leftover.unlink()
                except FileNotFoundError:
                    continue
                except OSError as cleanup:
                    print(f"note: could not remove {leftover}: {cleanup}", flush=True)


# ------------------------------------------------------------------ hooks

_active: ContextVar[RunCheckpoint | None] = ContextVar(
    "ract_run_checkpoint", default=None
)
_deferred: ContextVar[bool] = ContextVar("ract_run_checkpoint_deferred", default=False)


@contextmanager
def recording(checkpoint: RunCheckpoint) -> Iterator[RunCheckpoint]:
    """Bind *checkpoint* for the run; outside it every hook does nothing."""
    token = _active.set(checkpoint)
    try:
        yield checkpoint
    finally:
        _active.reset(token)


@contextmanager
def finish_deferred() -> Iterator[None]:
    """A step finishing in its worktree is not finished for the run yet."""
    token = _deferred.set(True)
    try:
        yield
    finally:
        _deferred.reset(token)


def plan_ready(plan: Plan) -> None:
    checkpoint = _active.get()
    if checkpoint is not None:
        checkpoint.plan_ready(plan)


def already_finished(n: int) -> bool:
    """True when step *n* finished in the run being resumed."""
    checkpoint = _active.get()
    return checkpoint is not None and checkpoint.is_finished(n)


def step_started(n: int) -> None:
    checkpoint = _active.get()
    if checkpoint is not None:
        checkpoint.step_started(n)


def step_finished(n: int) -> None:
    checkpoint = _active.get()
    if checkpoint is not None and not _deferred.get():
        checkpoint.step_finished(n)


def step_ended(n: int, outcome: str) -> None:
    checkpoint = _active.get()
    if checkpoint is not None:
        checkpoint.step_ended(n, outcome)


def note_worktree(step_id_hex: str) -> None:
    checkpoint = _active.get()
    if checkpoint is not None:
        checkpoint.note_worktree(step_id_hex)


def note_saving(backup: undo_backup.TurnBackup, key: str, full: Path) -> None:
    checkpoint = _active.get()
    if checkpoint is not None:
        checkpoint.note_saving(backup, key, full)


def note_written(root: Path | str, paths: Iterable[Path | str]) -> None:
    checkpoint = _active.get()
    if checkpoint is not None:
        checkpoint.note_written(root, paths)


# ------------------------------------------------------------------ resume


@dataclass
class ResetResult:
    undone: list[str] = field(default_factory=list)
    left: list[tuple[str, str]] = field(default_factory=list)


def _reset_worktree(root: Path, step_id_hex: str, result: ResetResult) -> None:
    from ract.executor.worktree import (
        Worktree,
        WorktreeError,
        WorktreeManager,
        _branch_name,
    )

    step_id = bytes.fromhex(step_id_hex) if len(step_id_hex) % 2 == 0 else b""
    if not step_id:
        result.left.append((step_id_hex, "not a step id; no worktree removed"))
        return
    manager = WorktreeManager(root)
    worktree = Worktree(
        step_id=step_id,
        path=manager.path_for(step_id),
        branch=_branch_name(step_id),
        parent_snapshot="",
    )
    try:
        manager.rollback(worktree)
    except WorktreeError as exc:
        result.left.append((worktree.branch, f"could not be removed: {exc}"))


def reset_in_progress(root: Path | str, state: dict[str, Any]) -> ResetResult:
    """Undo the partial change of the step that did not finish (D13 step 3).

    *state* is a checkpoint from ``load``. The step's worktree and branch
    are removed; on the user's files, what the step replaced is restored
    and what it created is removed, through the undo helpers so the
    resumed turn can be undone. A file that changed since the step wrote
    it is left as it is and named. The checkpoint on disk then records
    that nothing is in progress; *state* itself is not changed.
    """
    base = Path(os.path.realpath(root))
    result = ResetResult()
    progress = state["in_progress"]
    if progress is None:
        return result
    if progress["worktree"]:
        _reset_worktree(base, progress["worktree"], result)
    backup_id = progress["backup_id"]
    copies = (
        undo_backup.turns_dir(base).joinpath(
            backup_id, *_STEP_COPIES, str(progress["n"])
        )
        if backup_id
        else None
    )
    for entry in progress["files"]:
        key = entry["path"]
        why = undo_backup.check_entry(base, base, key)
        if why is not None:
            result.left.append((key, f"refused: {why}"))
            continue
        full = base / key
        if full.exists() and not full.is_file():
            result.left.append((key, "not a file now; left as it is"))
            continue
        current = _sha256(full)
        if current == entry["before"]:
            continue  # already as it was before the step
        if not entry["written"] or current != entry["after"]:
            result.left.append(
                (key, "changed after the interrupted step touched it; left as it is")
            )
            continue
        if entry["before"] is None:
            undo_backup.save_before_replace(base, [key])
            full.unlink()
            result.undone.append(key)
            continue
        source = copies / key if copies is not None else None
        if (
            source is None
            or undo_backup.check_entry(base, copies, key) is not None
            or source.is_symlink()
            or not source.is_file()
            or _sha256(source) != entry["before"]
        ):
            result.left.append((key, "its saved copy is gone; left as it is"))
            continue
        undo_backup.save_before_replace(base, [key])
        shutil.copyfile(source, full)
        result.undone.append(key)
    after = {**state, "in_progress": None}
    RunCheckpoint(base, state["run"], state["intent"], state=after)._write()
    return result


def resume_notices(state: dict[str, Any], reset: ResetResult) -> list[str]:
    """One line per step, shown before anything runs."""
    progress = state["in_progress"]
    interrupted = progress["n"] if progress is not None else None
    ended = progress.get("ended") if progress is not None else None
    how = {"refused": "was refused", "failed": "failed"}.get(ended, "was interrupted")
    lines = []
    for n in range(1, len(state["plan"]["steps"]) + 1):
        if n in state["finished"]:
            lines.append(f"step {n} done earlier, not run again")
        elif n == interrupted:
            undone = "its partial change was undone"
            if reset.left:
                undone += " except " + ", ".join(path for path, _ in reset.left)
            lines.append(f"step {n} {how}; {undone}; running it again")
        else:
            lines.append(f"step {n} next")
    return lines


__all__ = [
    "MAX_CHECKPOINT_BYTES",
    "SCHEMA",
    "CheckpointRefused",
    "ResetResult",
    "RunCheckpoint",
    "already_finished",
    "checkpoint_path",
    "finish_deferred",
    "load",
    "new_run_id",
    "note_saving",
    "note_worktree",
    "note_written",
    "plan_hash",
    "plan_ready",
    "recording",
    "reset_in_progress",
    "resume_notices",
    "runs_dir",
    "step_finished",
    "step_started",
    "stored_plan",
]
