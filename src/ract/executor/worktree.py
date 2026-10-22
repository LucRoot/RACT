"""Git worktree lifecycle for the substrate executor.

SUBSTRATE spec §3.2. Every step opens a worktree on a branch named
``rootact/step/<step_id_hex>``, derived from the loop's current parent
snapshot. Worktrees share the object store (see the ``git-worktree``
public documentation at ``https://git-scm.com/docs/git-worktree``), so
the per-step cost is dominated by checkout, not by cloning.

Lateral chain branch B: Windows filesystems are case-insensitive but
git's on-disk basename comparison is case-sensitive at the checkout
layer. Worktree roots normalize the basename against the expected casing
and refuse if the case drifts — this prevents the v0.2 ``RACT`` vs
``ract`` collision that trapped the earlier substrate attempt.

Lateral chain branch D: worktrees on abandoned plan branches are tagged
``rootact/abandoned/<step_id_hex>`` at rollback time so the run report
can list them without the git graph silently accumulating.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from ract.antilazy.pre_commit import (
        TestIntegrityGateOutcome,
        UnderEditGateOutcome,
    )
    from ract.antilazy.symgraph import SymbolGraph
    from ract.core.loop import WorkspaceSnapshot
    from ract.core.transaction import StepTransaction
    from ract.security.manifest import TestIntegrityConfig


class WorktreeError(RuntimeError):
    """Raised when a git-worktree operation fails or violates invariants."""


# ---------------------------------------------------------------------------
# Preconditions (lateral chain branch E)
# ---------------------------------------------------------------------------


def ensure_git_repo(root: Path) -> None:
    """Raise ``WorktreeError`` if ``root`` is not the top-level of a git repo.

    The substrate depends on git for snapshot, rollback, and branch-per-step
    isolation. A non-git workspace collapses the whole model, so the loop
    constructor refuses to enter (SUBSTRATE §3, depth-chain core dependency).
    """
    root = Path(root)
    if not root.is_dir():
        raise WorktreeError(
            f"workspace root does not exist or is not a directory: {root}"
        )
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise WorktreeError(
            f"workspace is not a git repository: {root} — the transactional "
            "substrate requires git for snapshot, rollback, and branch-per-step "
            "isolation. Run `git init` before entering the loop."
        )


def ensure_clean_tracked_tree(root: Path) -> None:
    """Raise if the working tree has uncommitted **tracked** changes.

    Untracked files are ignored — the substrate does not need them under
    version control to snapshot. Modified/deleted/staged tracked paths, on
    the other hand, would silently seed step 1 with state that is not part
    of ``parent_snapshot``. The error names the offending paths so the
    operator can commit or stash without guessing.
    """
    root = Path(root)
    # ``--porcelain=v1`` gives one line per changed path with a two-column
    # status prefix. ``?? `` lines are untracked; anything else is tracked.
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise WorktreeError(f"`git status` failed for {root}: {result.stderr.strip()}")
    dirty: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 3:
            continue
        status = line[:2]
        if status == "??":
            continue  # untracked — allowed
        dirty.append(line[3:])
    if dirty:
        joined = "\n  ".join(dirty)
        raise WorktreeError(
            "workspace has uncommitted tracked changes; the substrate needs "
            "a clean tracked tree so step 1's parent_snapshot is the HEAD "
            "commit and not silent working-tree state. Commit or stash "
            f"first. Offending paths:\n  {joined}"
        )


def resolve_head_sha(root: Path) -> str:
    """Return the full commit sha for ``HEAD`` at ``root``."""
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise WorktreeError(
            f"could not resolve HEAD for {root}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Worktree lifecycle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Worktree:
    """A live git worktree produced by ``WorktreeManager.create``."""

    step_id: bytes
    path: Path
    branch: str
    parent_snapshot: str


def _branch_name(step_id: bytes) -> str:
    return f"rootact/step/{step_id.hex()}"


def _abandoned_branch_name(step_id: bytes) -> str:
    """Lateral chain branch D: tag for step branches whose plan was abandoned."""
    return f"rootact/abandoned/{step_id.hex()}"


def _assert_case_match(path: Path) -> None:
    """Lateral chain branch B: refuse if the worktree basename case drifts.

    ``pathlib`` normalizes on Windows, but ``resolve()`` returns the
    filesystem's canonical casing. If the operator (or an upstream layer)
    passed us a differently-cased path, git worktree will accept it and
    then step-branch operations will silently work against a different
    on-disk directory when re-listed.
    """
    if not path.exists():
        return
    resolved = path.resolve()
    if resolved.name != path.name:
        raise WorktreeError(
            f"worktree path case drift detected: requested basename "
            f"{path.name!r}, on-disk basename {resolved.name!r}. This "
            "reproduces the v0.2 Windows RACT-vs-ract collision; refusing "
            "before the branch surface diverges."
        )


class WorktreeManager:
    """Create, list, and tear down step worktrees for a repo."""

    def __init__(self, repo_root: Path | str, *, worktree_root: Path | None = None):
        self.repo_root = Path(repo_root)
        # Default worktree root is *outside* the repo tree, under
        # `<repo>/.git/ract-worktrees/<step_id>`. Keeping worktrees outside
        # the main working directory prevents pytest / lint tools from
        # accidentally scanning them.
        self.worktree_root = (
            Path(worktree_root)
            if worktree_root is not None
            else self.repo_root / ".git" / "ract-worktrees"
        )

    # ----- construction -----

    def path_for(self, step_id: bytes) -> Path:
        return self.worktree_root / step_id.hex()

    def create(self, step_id: bytes, parent_snapshot: str) -> Worktree:
        """Shell to ``git worktree add`` and return a ``Worktree`` handle.

        Uses ``git worktree add <path> -b <branch> <parent_snapshot>`` per
        the git-worktree docs (public reference cited in the module
        docstring). The branch is created off ``parent_snapshot`` so the
        step transaction is anchored to a known commit.
        """
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        target = self.path_for(step_id)
        _assert_case_match(target)
        branch = _branch_name(step_id)
        cmd = [
            "git",
            "-C",
            str(self.repo_root),
            "worktree",
            "add",
            str(target),
            "-b",
            branch,
            parent_snapshot,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise WorktreeError(
                f"git worktree add failed for step {step_id.hex()}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return Worktree(
            step_id=step_id,
            path=target,
            branch=branch,
            parent_snapshot=parent_snapshot,
        )

    # ----- inspection -----

    def list_active(self) -> list[str]:
        """Return the branch names ``git branch --list rootact/step/*`` reports.

        Verified by ``test_worktree_names_are_discoverable``: the branch
        naming discipline is what makes gc trivial later (lateral chain
        branch C, deferred).
        """
        result = subprocess.run(
            ["git", "-C", str(self.repo_root), "branch", "--list", "rootact/step/*"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise WorktreeError(f"git branch --list failed: {result.stderr.strip()}")
        branches: list[str] = []
        for line in result.stdout.splitlines():
            branch = line.strip().lstrip("*").strip()
            if branch:
                branches.append(branch)
        return branches

    def worktree_list(self) -> list[dict[str, str]]:
        """Return ``git worktree list --porcelain`` parsed into records."""
        result = subprocess.run(
            ["git", "-C", str(self.repo_root), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise WorktreeError(f"git worktree list failed: {result.stderr.strip()}")
        records: list[dict[str, str]] = []
        current: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if not line.strip():
                if current:
                    records.append(current)
                    current = {}
                continue
            key, _, value = line.partition(" ")
            current[key] = value
        if current:
            records.append(current)
        return records

    # ----- lifecycle -----

    def commit(self, wt: Worktree, message: str) -> str:
        """Stage all changes in the worktree and commit; return the new sha."""
        add = subprocess.run(
            ["git", "-C", str(wt.path), "add", "-A"],
            capture_output=True,
            text=True,
            check=False,
        )
        if add.returncode != 0:
            raise WorktreeError(f"git add failed in {wt.path}: {add.stderr.strip()}")
        commit = subprocess.run(
            [
                "git",
                "-C",
                str(wt.path),
                # ``--allow-empty`` because a step whose only observable
                # effect is that its post-conditions now hold (say, a config
                # tweak we already committed elsewhere) should still record
                # the intent — auditors reading the git graph should see
                # every step's transaction, not only the ones that added
                # bytes.
                "commit",
                "--allow-empty",
                "-m",
                message,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if commit.returncode != 0:
            raise WorktreeError(
                f"git commit failed in {wt.path}: {commit.stderr.strip()}"
            )
        sha_result = subprocess.run(
            ["git", "-C", str(wt.path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if sha_result.returncode != 0:
            raise WorktreeError(
                f"git rev-parse HEAD failed in {wt.path}: {sha_result.stderr.strip()}"
            )
        return sha_result.stdout.strip()

    # ----- ALM module_03 pre-commit hooks (G5 + G6) -----
    #
    # These delegate to ``ract.antilazy.pre_commit`` so the WorktreeManager
    # stays thin — the transactional executor holds the merge site, and
    # the ALM helpers hold the analyzer. Callers wire the hooks in front
    # of ``commit`` on the pre-commit path. Both are pure over their
    # inputs; tests drive them without a live worktree.
    def _check_test_integrity(
        self,
        transaction: "StepTransaction",
        parent_snapshot: "WorkspaceSnapshot",
        child_snapshot: "WorkspaceSnapshot",
        *,
        config: "TestIntegrityConfig | None" = None,
        handshake_approved: bool = False,
    ) -> "TestIntegrityGateOutcome":
        """Run G5 for ``transaction`` and return the ``TestIntegrityGateOutcome``.

        Any hard-block violation not covered by an operator handshake
        surfaces ``should_roll_back=True``; the caller performs the
        actual rollback via ``WorktreeManager.rollback``. See
        ``ract.antilazy.pre_commit.enforce_g5``.

        Second Pass Cycle-2 fix: annotations were loosened to
        ``object`` in the first-build to avoid the executor→antilazy
        import cycle. The TYPE_CHECKING guard at the top of this
        module carries the real types now; mypy sees the shape,
        runtime imports remain deferred.
        """
        # Local import breaks the executor→antilazy cycle at import time.
        from ract.antilazy.pre_commit import enforce_g5

        return enforce_g5(
            transaction,
            parent_snapshot,
            child_snapshot,
            config=config,
            handshake_approved=handshake_approved,
        )

    def _check_under_edit(
        self,
        transaction: "StepTransaction",
        graph: "SymbolGraph",
        edited_symbols: "Iterable[str]",
        *,
        edited_files: "Iterable[str]" = (),
        passing_tests_touched: "Iterable[str]" = (),
        declared_unaffected: "Iterable[str]" = (),
    ) -> "UnderEditGateOutcome":
        """Run G6 for ``transaction`` and return the ``UnderEditGateOutcome``.

        Any uncovered downstream caller not marked declared / covered
        by test / covered by edit surfaces ``should_roll_back=True``.
        """
        from ract.antilazy.pre_commit import enforce_g6

        return enforce_g6(
            transaction,
            graph,
            edited_symbols,
            edited_files=edited_files,
            passing_tests_touched=passing_tests_touched,
            declared_unaffected=declared_unaffected,
        )

    def rollback(self, wt: Worktree, *, abandon: bool = False) -> None:
        """Remove the worktree and its branch (or tag it abandoned).

        ``abandon=True`` renames ``rootact/step/<sid>`` to
        ``rootact/abandoned/<sid>`` before removing the on-disk tree, so
        the run report (lateral chain branch D) can enumerate abandoned
        step branches without them polluting the ``rootact/step/*``
        namespace.
        """
        remove = subprocess.run(
            [
                "git",
                "-C",
                str(self.repo_root),
                "worktree",
                "remove",
                "--force",
                str(wt.path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        # Missing worktree is not fatal — the caller may have already
        # removed the directory (e.g. inside a container tear-down).
        if remove.returncode != 0 and "is not a working tree" not in (
            remove.stderr + remove.stdout
        ):
            raise WorktreeError(
                f"git worktree remove failed for {wt.path}: "
                f"{remove.stderr.strip() or remove.stdout.strip()}"
            )
        if abandon:
            rename = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.repo_root),
                    "branch",
                    "-M",
                    wt.branch,
                    _abandoned_branch_name(wt.step_id),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if rename.returncode != 0:
                raise WorktreeError(
                    f"git branch rename to abandoned failed for {wt.branch}: "
                    f"{rename.stderr.strip()}"
                )
        else:
            # Drop the branch entirely; a rolled-back step must leave no
            # dangling branch per DoD ("rolled-back steps leave no branch").
            delete = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.repo_root),
                    "branch",
                    "-D",
                    wt.branch,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            # A missing branch is fine — the transaction may never have
            # advanced past ``create``.
            if delete.returncode != 0 and "not found" not in (
                delete.stderr + delete.stdout
            ):
                raise WorktreeError(
                    f"git branch -D failed for {wt.branch}: "
                    f"{delete.stderr.strip() or delete.stdout.strip()}"
                )


def _git_in(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _git_bytes(
    repo: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run git and keep stdout as bytes (file contents, patches)."""
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=False, env=env
    )


def _literal(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command whose path arguments are file names, not pathspecs.

    LR:: Without this, ``lib/[ab].py`` is a glob and ``:x`` is pathspec
    magic, so a per-file check could match a different file (AUD-011).
    """
    return _git_in(repo, "--literal-pathspecs", *args)


# Paths a base snapshot never contains, so they never reach a step worktree:
# RACT's own state, and files that usually hold secrets (an untracked .env
# that is not ignored would otherwise be copied into the worktree).
_SNAPSHOT_EXCLUDES = (
    ".ract",
    ":(glob)**/.env",
    ":(glob)**/.env.*",
    ":(glob)**/*.pem",
    ":(glob)**/*.key",
    ":(glob)**/id_rsa",
    ":(glob)**/id_ed25519",
)


def snapshot_working_tree(repo: Path) -> str:
    """Commit the working tree as it is now, without touching the operator's git state.

    LR:: A step's worktree used to start from HEAD, and a run refused a tree
    with uncommitted tracked changes. After RACT applied a step as unstaged
    edits, the next run hit that refusal and silently fell back to writing in
    place without isolation (AUD-002), and a later step could not see files an
    earlier step had created (AUD-001). The base is now a commit of the
    working tree itself: tracked changes and untracked, not-ignored files,
    minus ``.ract/`` and secret-shaped files. It is built in a temporary
    index (``GIT_INDEX_FILE``), so the operator's index, branch, stash and
    working tree are unchanged; the commit is referenced only by the step
    branches made from it. ADR-0047 D6.

    Raises ``WorktreeError`` when git cannot build it.
    """
    import os as _os
    import tempfile as _tempfile

    head = _git_in(repo, "rev-parse", "--verify", "-q", "HEAD")
    head_sha = head.stdout.strip() if head.returncode == 0 else ""
    fd, index_path = _tempfile.mkstemp(prefix="ract-index-")
    _os.close(fd)
    _os.unlink(index_path)  # git creates it; an empty file is not a valid index
    env = dict(_os.environ)
    env["GIT_INDEX_FILE"] = index_path
    try:
        if head_sha:
            _git_bytes(repo, "read-tree", head_sha, env=env)
        add = _git_bytes(repo, "add", "-A", "--", ".", env=env)
        if add.returncode != 0:
            raise WorktreeError(
                "could not snapshot the working tree: "
                + add.stderr.decode("utf-8", "replace").strip()
            )
        # Then drop RACT state and secret-shaped files from the snapshot
        # index (only this temporary index; the operator's is untouched).
        _git_bytes(
            repo,
            "rm",
            "-r",
            "-q",
            "--cached",
            "--ignore-unmatch",
            "--",
            *_SNAPSHOT_EXCLUDES,
            env=env,
        )
        tree = _git_bytes(repo, "write-tree", env=env)
        if tree.returncode != 0:
            raise WorktreeError("could not write the snapshot tree")
        commit_args = [
            "commit-tree",
            tree.stdout.decode().strip(),
            "-m",
            "ract: base snapshot of the working tree",
        ]
        if head_sha:
            commit_args[2:2] = ["-p", head_sha]
        identity = dict(env)
        identity.setdefault("GIT_AUTHOR_NAME", "ract")
        identity.setdefault("GIT_AUTHOR_EMAIL", "ract@localhost")
        identity.setdefault("GIT_COMMITTER_NAME", "ract")
        identity.setdefault("GIT_COMMITTER_EMAIL", "ract@localhost")
        identity.pop("GIT_INDEX_FILE", None)
        commit = _git_bytes(repo, *commit_args, env=identity)
        if commit.returncode != 0:
            raise WorktreeError(
                "could not commit the snapshot: "
                + commit.stderr.decode("utf-8", "replace").strip()
            )
        return commit.stdout.decode().strip()
    finally:
        for leftover in (index_path, index_path + ".lock"):
            try:
                _os.unlink(leftover)
            except OSError:
                pass


@dataclass(frozen=True)
class WorkingTreeApply:
    """What ``apply_commit_to_working_tree`` did.

    ``skipped`` maps each path left alone to the reason, in plain words.
    ``patch_path`` is the saved patch for the skipped paths, relative to the
    repository, or "" when nothing was skipped.
    """

    applied: tuple[str, ...]
    skipped: dict[str, str]
    patch_path: str


def changed_path_additions(
    repo: Path, before: str, after: str, applied: tuple[str, ...]
) -> set[str]:
    """Paths a step added (status A) that were applied to the working tree."""
    listing = _git_in(
        repo,
        "diff",
        "--name-status",
        "--no-renames",
        "--diff-filter=A",
        "-z",
        before,
        after,
    )
    fields = [f for f in listing.stdout.split("\0") if f]
    added = set(fields[1::2])
    return {path for path in applied if path in added}


def _blob_of_working_file(repo: Path, path: str) -> str | None:
    """Blob id git would store for the working file (clean filters applied)."""
    result = _literal(repo, "hash-object", "--path", path, "--", path)
    return result.stdout.strip() if result.returncode == 0 else None


def _blob_in(repo: Path, commit: str, path: str) -> str | None:
    result = _git_in(repo, "rev-parse", "--verify", "-q", f"{commit}:{path}")
    return result.stdout.strip() if result.returncode == 0 else None


def _classify_for_apply(
    repo: Path,
    status: str,
    path: str,
    before: str,
    created_by_run: frozenset[str] = frozenset(),
) -> str:
    """Return "write", "delete", "noop", or a reason the path is a conflict.

    LR:: Safety is decided by content, not by git's tracking state. A path
    is safe to change only when the working file still equals the step's
    base (``before``), which is a snapshot of the working tree when the
    step started, so files an earlier step applied count as unchanged
    (AUD-001). An earlier version asked whether the path was tracked and
    refused step 1's new files; the version before that asked ``git diff``,
    which ignores untracked files and overwrote one. Anything that cannot be
    classified is a conflict.
    """
    from ract.workspace_path import resolve_workspace_path  # noqa: PLC0415

    kind = status[:1]
    if kind not in {"A", "M", "D"}:
        return f"change type {status!r} is not applied automatically"
    resolved = resolve_workspace_path(repo, path, purpose="write")
    if resolved.value is None:
        return resolved.error or "path refused"
    full = resolved.value
    exists = os.path.lexists(full)
    if exists and (os.path.islink(full) or os.path.isdir(full)):
        return "a directory or link is at that path in your working tree"
    if kind == "A":
        return (
            "a file already exists at that path in your working tree"
            if exists
            else "write"
        )
    base_blob = _blob_in(repo, before, path)
    if not exists:
        return "noop" if kind == "D" else "you deleted this file during the step"
    if base_blob is None:
        return "the step's starting point has no copy of this file to compare with"
    if _blob_of_working_file(repo, path) != base_blob:
        return "you changed this file during the step"
    tracked = _literal(repo, "ls-files", "--error-unmatch", "--", path).returncode == 0
    if not tracked and path not in created_by_run:
        # git keeps no copy of an untracked file the operator made, so a
        # change to it could not be undone from git. Files an earlier step of
        # this run created are untracked too, and those may change (AUD-001).
        return "the file is yours and untracked, so git has no copy to restore it from"
    return "delete" if kind == "D" else "write"


def apply_commit_to_working_tree(
    repo: Path,
    before: str,
    after: str,
    *,
    created_by_run: frozenset[str] = frozenset(),
) -> WorkingTreeApply:
    """Copy a step commit's changes into the working tree, without touching the index.

    LR:: S-011 stopgap until ADR-0047 D6 (review, then apply). The step was
    committed on its own branch. Each changed file is written from the step
    commit through ``git cat-file --filters``, so git's line-ending and
    smudge rules apply, while HEAD, the branch and the index are never
    touched: a file the operator staged keeps its staged version (AUD-010).
    RACT's ``.ract/`` state is never copied.

    Nothing the operator has is overwritten or deleted. A path is applied only
    when it is absent (for an addition), or when the working file still
    equals the step's base (for a change or deletion). Every other state, and
    any error on a path, leaves that path alone with a reason (AUD-009); the
    step's patch for those paths is saved under ``.ract/pending/`` as bytes,
    so ``git apply`` works for binary and non-UTF-8 files (AUD-004).
    """
    if not before or not after or before == after:
        return WorkingTreeApply((), {}, "")
    listing = _git_in(
        repo,
        "diff",
        "--name-status",
        "--no-renames",
        "-z",
        before,
        after,
        "--",
        ".",
        ":(exclude).ract",
    )
    if listing.returncode != 0:
        # A failed listing must not read as "the step changed nothing" (AUD-012).
        return WorkingTreeApply(
            (),
            {
                "(all paths)": f"git could not list the step's changes: {listing.stderr.strip()}"
            },
            "",
        )
    fields = [f for f in listing.stdout.split("\0") if f]
    changes = list(zip(fields[0::2], fields[1::2]))
    applied: list[str] = []
    skipped: dict[str, str] = {}
    for status, path in changes:
        try:
            verdict = _classify_for_apply(repo, status, path, before, created_by_run)
            if verdict == "noop":
                applied.append(path)
            elif verdict == "delete":
                (repo / path).unlink()
                applied.append(path)
            elif verdict == "write":
                content = _git_bytes(repo, "cat-file", "--filters", f"{after}:{path}")
                if content.returncode != 0:
                    skipped[path] = "git could not read the step's version of this file"
                    continue
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content.stdout)
                applied.append(path)
            else:
                skipped[path] = verdict
        except OSError as exc:
            skipped[path] = f"could not change it: {exc.strerror or exc}"
    patch_path = ""
    real_skips = [p for p in skipped if p != "(all paths)"]
    if real_skips:
        pending = repo / ".ract" / "pending"
        pending.mkdir(parents=True, exist_ok=True)
        target = pending / f"{after[:12]}.patch"
        diff = _git_bytes(
            repo,
            "--literal-pathspecs",
            "diff",
            "--binary",
            before,
            after,
            "--",
            *real_skips,
        )
        target.write_bytes(diff.stdout)
        patch_path = target.relative_to(repo).as_posix()
    return WorkingTreeApply(tuple(applied), skipped, patch_path)


# ---------------------------------------------------------------------------
# Repository housekeeping (board S-016)
# ---------------------------------------------------------------------------

STEP_BRANCH_PREFIX = "rootact/step/"


def ensure_ract_dir_excluded(repo: Path) -> bool:
    """Add ``.ract/`` to the repository's local exclude file, once.

    LR:: RACT keeps its state in ``.ract/``, which showed up as untracked in
    every ``git status``. ``.git/info/exclude`` is local to this clone and is
    never committed, so the operator's ``.gitignore`` is left alone. RACT
    itself writes this one line; model tools may never write under ``.git``
    (ADR-0047 D3). The path comes from ``git rev-parse --git-path`` so a
    linked worktree, whose ``.git`` is a file, is handled.

    Returns True when the line was added, False when it was already there or
    ``repo`` is not a git repository.
    """
    found = _git_in(repo, "rev-parse", "--git-path", "info/exclude")
    if found.returncode != 0 or not found.stdout.strip():
        return False
    exclude = Path(found.stdout.strip())
    if not exclude.is_absolute():
        exclude = Path(repo) / exclude
    existing = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    if any(
        line.strip() in {".ract/", ".ract", "/.ract/", "/.ract"}
        for line in existing.splitlines()
    ):
        return False
    exclude.parent.mkdir(parents=True, exist_ok=True)
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    with exclude.open("a", encoding="utf-8") as handle:
        handle.write(f"{prefix}# RACT state (local, added by ract)\n.ract/\n")
    return True


@dataclass(frozen=True)
class StepBranch:
    """A ``rootact/step/*`` branch and the age of its tip commit."""

    name: str
    age_days: float


def list_step_branches(repo: Path, *, now: float | None = None) -> list[StepBranch]:
    """Every ``rootact/step/*`` branch, oldest first."""
    import time as _time

    listing = _git_in(
        repo,
        "for-each-ref",
        "--format=%(refname:short) %(committerdate:unix)",
        f"refs/heads/{STEP_BRANCH_PREFIX}",
    )
    current = now if now is not None else _time.time()
    branches: list[StepBranch] = []
    for line in listing.stdout.splitlines():
        name, _, stamp = line.rpartition(" ")
        try:
            age = max(0.0, (current - int(stamp)) / 86400.0)
        except ValueError:
            continue
        branches.append(StepBranch(name, age))
    return sorted(branches, key=lambda b: -b.age_days)


def prune_step_branches(repo: Path, older_than_days: float) -> list[str]:
    """Delete ``rootact/step/*`` branches whose tip is older than the limit.

    Only RACT's own step branches, never the checked-out branch. Each step
    branch is the record of what one step committed, so this runs only when
    the operator asks (``ract doctor --prune-step-branches``).
    """
    checked_out = _git_in(repo, "branch", "--show-current").stdout.strip()
    deleted: list[str] = []
    for branch in list_step_branches(repo):
        if branch.age_days < older_than_days or branch.name == checked_out:
            continue
        if not branch.name.startswith(STEP_BRANCH_PREFIX):
            continue
        if _git_in(repo, "branch", "-D", "--", branch.name).returncode == 0:
            deleted.append(branch.name)
    return deleted


# RACT 0.4.0
