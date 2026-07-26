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

import subprocess
from dataclasses import dataclass
from pathlib import Path


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
        raise WorktreeError(
            f"`git status` failed for {root}: {result.stderr.strip()}"
        )
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
            raise WorktreeError(
                f"git branch --list failed: {result.stderr.strip()}"
            )
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
            raise WorktreeError(
                f"git worktree list failed: {result.stderr.strip()}"
            )
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
            raise WorktreeError(
                f"git add failed in {wt.path}: {add.stderr.strip()}"
            )
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


# RACT 0.4.0
