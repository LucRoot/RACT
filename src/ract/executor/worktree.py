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
from typing import TYPE_CHECKING, Callable, Iterable

from ract.workspace_path import (
    ENV_TEMPLATE_SUFFIXES,
    SECRET_NAME_GLOBS,
    is_secret_shaped,
)
from ract import run_checkpoint, undo_backup

if TYPE_CHECKING:
    from ract.antilazy.pre_commit import (
        TestIntegrityGateOutcome,
        UnderEditGateOutcome,
    )
    from ract.antilazy.symgraph import SymbolGraph
    from ract.core.loop import WorkspaceSnapshot
    from ract.core.transaction import StepTransaction
    from ract.security.manifest import TestIntegrityConfig


# The identity on every commit RACT makes (step commits and base snapshots).
# LR:: A plain `git commit` took user.name and user.email from the machine,
# so a personal or employer identity landed in objects on rootact/step/*
# branches the operator may push, and on a machine with no identity (a
# fresh CI runner) the step failed with "Author identity unknown" (S-024).
# The environment variables win over any git config and over values the
# operator's environment already sets; commit signing is off so a signing
# setup cannot prompt or hang a step.
RACT_GIT_NAME = "ract"
RACT_GIT_EMAIL = "ract@localhost"
_NO_SIGNING = ("-c", "commit.gpgsign=false")


def _no_hooks() -> tuple[str, str]:
    """``-c core.hooksPath=<empty directory>``: run none of the operator's hooks.

    LR:: Step worktrees share the repository's hooks. The operator's
    pre-commit hook ran on every RACT step commit (a failing hook failed
    every step), and post-checkout ran on every `git worktree add` (G-038).
    Step commits are RACT's transaction records; the operator's hooks belong
    to the operator's own commit when the change reaches their branch. An
    empty hooks directory disables every hook, post-commit and post-checkout
    included, where `--no-verify` covers only pre-commit and commit-msg.
    """
    global _EMPTY_HOOKS_DIR
    if _EMPTY_HOOKS_DIR is None or not Path(_EMPTY_HOOKS_DIR).is_dir():
        import tempfile

        _EMPTY_HOOKS_DIR = tempfile.mkdtemp(prefix="ract-no-hooks-")
    return ("-c", f"core.hooksPath={_EMPTY_HOOKS_DIR}")


_EMPTY_HOOKS_DIR: str | None = None


def ract_commit_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """``base`` (default: this process's environment) with RACT's identity."""
    env = dict(os.environ if base is None else base)
    env["GIT_AUTHOR_NAME"] = RACT_GIT_NAME
    env["GIT_AUTHOR_EMAIL"] = RACT_GIT_EMAIL
    env["GIT_COMMITTER_NAME"] = RACT_GIT_NAME
    env["GIT_COMMITTER_EMAIL"] = RACT_GIT_EMAIL
    return env


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
            *_no_hooks(),
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
        _write_owner(target)
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
                *_NO_SIGNING,
                *_no_hooks(),
                # ``--allow-empty`` because a step whose only observable
                # effect is that its post-conditions now hold (say, a config
                # tweak we already committed elsewhere) should still record
                # the intent — auditors reading the git graph should see
                # every step's transaction, not only the ones that added
                # bytes.
                "commit",
                "--allow-empty",
                "--no-verify",
                "-m",
                message,
            ],
            capture_output=True,
            text=True,
            check=False,
            env=ract_commit_env(),
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

    def leftovers(self) -> list[Path]:
        """Step worktrees still registered under this manager's root."""
        return [
            p for p in _registered(self.repo_root) if p.parent == self.worktree_root
        ]

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
        if remove.returncode != 0 and "is not a working tree" in (
            remove.stderr + remove.stdout
        ):
            # B-146 (Linux): a Ctrl-C reaches the step's git too, and a
            # worktree add cut short leaves a registration whose folder is
            # gone or half made; prune drops it, or it stays listed.
            _git_in(self.repo_root, "worktree", "prune")
        elif remove.returncode != 0:
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
# B-205: built from the one list in workspace_path, so a name the model may
# not see is never copied into a step's worktree either.
_SNAPSHOT_EXCLUDES = (
    ".ract",
    *(f":(glob,icase)**/{pattern}" for pattern in SECRET_NAME_GLOBS),
    # D-014: committed placeholders stay in the snapshot, any case.
    *(f":(exclude,glob,icase)**/.env*.{suffix}" for suffix in ENV_TEMPLATE_SUFFIXES),
)


SNAPSHOT_MAX_FILE_BYTES = 2 * 1024 * 1024
SNAPSHOT_MAX_UNTRACKED = 2_000
SNAPSHOT_BUDGET_SECONDS = 20.0
_UNTRACKED_BATCH = 200
_BATCH_GRACE_SECONDS = 10.0
_PROGRESS_AFTER_SECONDS = 2.0


@dataclass(frozen=True)
class Snapshot:
    """A base snapshot commit and the files it left out, with the reason for each."""

    sha: str
    left_out: tuple[str, ...] = ()
    too_large: tuple[str, ...] = ()
    over_count: tuple[str, ...] = ()
    over_time: tuple[str, ...] = ()
    max_file_bytes: int = SNAPSHOT_MAX_FILE_BYTES
    max_untracked: int = SNAPSHOT_MAX_UNTRACKED
    budget: float = SNAPSHOT_BUDGET_SECONDS

    def notice(self, *, names: int = 10) -> str:
        """One line for the operator, or "" when nothing was left out."""
        if not self.left_out:
            return ""
        parts = []
        if self.too_large:
            parts.append(
                f"{len(self.too_large):,} over {_size_label(self.max_file_bytes)}"
            )
        if self.over_count:
            parts.append(
                f"{len(self.over_count):,} past the first "
                f"{self.max_untracked:,} untracked files"
            )
        if self.over_time:
            parts.append(f"{len(self.over_time):,} not reached in {self.budget:g} s")
        shown = ", ".join(self.left_out[:names])
        more = len(self.left_out) - names
        if more > 0:
            shown += f" and {more:,} more"
        return (
            f"note: {len(self.left_out):,} "
            f"{'file' if len(self.left_out) == 1 else 'files'} left out of this "
            "run's snapshot "
            f"({'; '.join(parts)}), so the run cannot see or change them: {shown}. "
            "Add generated, vendored or large files to .gitignore."
        )


def _size_label(size: int) -> str:
    mib = size / (1024 * 1024)
    return f"{mib:g} MiB" if mib >= 1 else f"{size:,} bytes"


def _untracked_files(repo: Path) -> list[str]:
    """Untracked, not ignored files, shallowest first."""
    listing = _git_in(repo, "ls-files", "-z", "--others", "--exclude-standard")
    names = [n for n in listing.stdout.split("\0") if n]
    return sorted(names, key=lambda n: (n.count("/"), n))


def _modified_tracked(repo: Path) -> list[str]:
    listing = _git_in(repo, "diff", "--name-only", "-z")
    return [n for n in listing.stdout.split("\0") if n]


def _over_size(repo: Path, names: Iterable[str], max_file_bytes: int) -> list[str]:
    large = []
    for name in names:
        try:
            if (Path(repo) / name).stat().st_size > max_file_bytes:
                large.append(name)
        except OSError:
            continue
    return large


def _is_snapshot_excluded(name: str) -> bool:
    first = name.split("/", 1)[0]
    return first == ".ract" or is_secret_shaped(name)


def take_snapshot(
    repo: Path,
    *,
    max_file_bytes: int = SNAPSHOT_MAX_FILE_BYTES,
    max_untracked: int = SNAPSHOT_MAX_UNTRACKED,
    budget: float = SNAPSHOT_BUDGET_SECONDS,
    progress: Callable[[str], None] | None = None,
) -> Snapshot:
    """Commit the working tree as it is now, without touching the operator's git state.

    LR:: A step's worktree used to start from HEAD, and a run refused a tree
    with uncommitted tracked changes. After RACT applied a step as unstaged
    edits, the next run hit that refusal and silently fell back to writing in
    place without isolation (AUD-002), and a later step could not see files an
    earlier step had created (AUD-001). The base is now a commit of the
    working tree itself: tracked changes and untracked, not-ignored files,
    minus ``.ract/`` and secret-shaped files. It is built in a temporary index
    (``GIT_INDEX_FILE``) that starts as a copy of the operator's index, so
    unchanged tracked files keep git's stat cache and are not re-hashed; the
    operator's index, branch, stash and files are unchanged. The temporary
    index is removed on every path. ADR-0047 D6.

    Limits (S-011c): hashing a file costs a few milliseconds, and the first
    read of a freshly written file costs more, so a project that was never
    committed, or one with build output missing from .gitignore, took over a
    minute with no message (10,000 small untracked files: 65 s). Files over
    ``max_file_bytes`` are left out; untracked files are added shallowest
    first, at most ``max_untracked`` of them, in batches, and adding stops
    when ``budget`` seconds have passed. Everything left out is listed on the
    result with its reason (``Snapshot.notice``), and the apply refuses any
    step change to it. ``progress`` gets a line every two seconds once the
    snapshot has run for two seconds.

    Raises ``WorktreeError`` when git fails, or when the tracked changes
    alone cannot be added within ``budget``.
    """
    import os as _os
    import shutil as _shutil
    import tempfile as _tempfile
    import time as _time

    started = _time.monotonic()
    head = _git_in(repo, "rev-parse", "--verify", "-q", "HEAD")
    head_sha = head.stdout.strip() if head.returncode == 0 else ""
    untracked = [n for n in _untracked_files(repo) if not _is_snapshot_excluded(n)]
    too_large = _over_size(repo, untracked, max_file_bytes)
    modified_tracked = _modified_tracked(repo)
    tracked_large = _over_size(repo, modified_tracked, max_file_bytes)
    large_set = set(too_large)
    untracked = [n for n in untracked if n not in large_set]
    over_count = untracked[max_untracked:]
    untracked = untracked[:max_untracked]
    over_time: list[str] = []
    tmp_dir = _tempfile.mkdtemp(prefix="ract-snapshot-")
    index_path = _os.path.join(tmp_dir, "index")
    env = dict(_os.environ)
    env["GIT_INDEX_FILE"] = index_path
    last_progress = started

    def remaining() -> float:
        return budget - (_time.monotonic() - started)

    try:
        operator_index = _git_in(
            repo, "rev-parse", "--git-path", "index"
        ).stdout.strip()
        operator_index_path = Path(operator_index)
        if not operator_index_path.is_absolute():
            operator_index_path = Path(repo) / operator_index_path
        if operator_index_path.is_file():
            _shutil.copyfile(operator_index_path, index_path)
        elif head_sha:
            _git_bytes(repo, "read-tree", head_sha, env=env)
        if modified_tracked:
            excludes = [f":(exclude,literal){name}" for name in tracked_large]
            try:
                add = subprocess.run(
                    ["git", "-C", str(repo), "add", "-u", "--", ".", *excludes],
                    capture_output=True,
                    check=False,
                    env=env,
                    timeout=max(remaining(), 1.0),
                )
            except subprocess.TimeoutExpired as exc:
                raise WorktreeError(
                    "snapshotting your uncommitted changes took longer than "
                    f"{budget:.0f} s; add large generated or data directories "
                    "to .gitignore"
                ) from exc
            if add.returncode != 0:
                raise WorktreeError(
                    "could not snapshot the working tree: "
                    + add.stderr.decode("utf-8", "replace").strip()
                )
        done = 0
        for i in range(0, len(untracked), _UNTRACKED_BATCH):
            batch = untracked[i : i + _UNTRACKED_BATCH]
            if remaining() <= 0:
                over_time = untracked[i:]
                break
            try:
                added = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(repo),
                        "--literal-pathspecs",
                        "add",
                        "--pathspec-from-file=-",
                        "--pathspec-file-nul",
                    ],
                    input="\0".join(batch).encode("utf-8"),
                    capture_output=True,
                    check=False,
                    env=env,
                    # The budget decides whether a batch starts; a batch that
                    # has started gets time to finish (one is about 0.1 s,
                    # several seconds under heavy load). Killing it at the
                    # budget's edge threw the work away (G-020 gate failure).
                    timeout=max(remaining(), 0.0) + _BATCH_GRACE_SECONDS,
                )
            except subprocess.TimeoutExpired:
                # git writes the index only at the end, so this batch is not
                # in it. A killed git leaves index.lock beside the temporary
                # index, and write-tree then fails; the lock is ours to remove.
                Path(index_path + ".lock").unlink(missing_ok=True)
                over_time = untracked[i:]
                break
            if added.returncode != 0:
                raise WorktreeError(
                    "could not snapshot the working tree: "
                    + added.stderr.decode("utf-8", "replace").strip()
                )
            done += len(batch)
            now = _time.monotonic()
            if (
                progress is not None
                and now - started >= _PROGRESS_AFTER_SECONDS
                and now - last_progress >= _PROGRESS_AFTER_SECONDS
            ):
                progress(
                    f"snapshotting your working tree: {done:,} of "
                    f"{len(untracked):,} untracked files"
                )
                last_progress = now
        # Drop RACT state and secret-shaped files from the snapshot index
        # (only this temporary index; the operator's is untouched).
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
            raise WorktreeError(
                "could not write the snapshot tree: "
                + tree.stderr.decode("utf-8", "replace").strip()
            )
        commit_args = [
            "commit-tree",
            tree.stdout.decode().strip(),
            "-m",
            "ract: base snapshot of the working tree",
        ]
        if head_sha:
            commit_args[2:2] = ["-p", head_sha]
        identity = ract_commit_env(env)
        identity.pop("GIT_INDEX_FILE", None)
        commit = _git_bytes(repo, *_NO_SIGNING, *commit_args, env=identity)
        if commit.returncode != 0:
            raise WorktreeError(
                "could not commit the snapshot: "
                + commit.stderr.decode("utf-8", "replace").strip()
            )
        return Snapshot(
            commit.stdout.decode().strip(),
            left_out=tuple(too_large + tracked_large + over_count + over_time),
            too_large=tuple(too_large + tracked_large),
            over_count=tuple(over_count),
            over_time=tuple(over_time),
            max_file_bytes=max_file_bytes,
            max_untracked=max_untracked,
            budget=budget,
        )
    finally:
        _shutil.rmtree(tmp_dir, ignore_errors=True)


def snapshot_working_tree(repo: Path) -> str:
    """Commit id of ``take_snapshot(repo)``."""
    return take_snapshot(repo).sha


@dataclass(frozen=True)
class WorkingTreeApply:
    """What ``apply_commit_to_working_tree`` did.

    ``skipped`` maps each path left alone to the reason, in plain words.
    ``patch_path`` is the saved patch for the skipped paths, relative to the
    repository, or "" when nothing was skipped. ``added`` holds the applied
    paths the step created (status A), read from the same listing; a second
    ``git diff`` for them cost a process start per step (B-045).
    """

    applied: tuple[str, ...]
    skipped: dict[str, str]
    patch_path: str
    added: frozenset[str] = frozenset()


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
    left_out: frozenset[str] = frozenset(),
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
    if path in left_out or is_secret_shaped(path):
        # The step never saw this file (left out of its snapshot), so it
        # cannot have a valid change to it.
        return "RACT left this file out of the step's snapshot and does not change it"
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


def _sidecar_of(path: str) -> str:
    """The Rootknot sidecar path beside *path* (``src/.calc.py.rootknot.json``)."""
    head, _, name = path.rpartition("/")
    return f"{head}/.{name}.rootknot.json" if head else f".{name}.rootknot.json"


def apply_commit_to_working_tree(
    repo: Path,
    before: str,
    after: str,
    *,
    created_by_run: frozenset[str] = frozenset(),
    left_out: frozenset[str] = frozenset(),
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
    # S-015b: a Rootknot sidecar is RACT's record of its artifact. When the
    # step changes both, the sidecar a previous run wrote (untracked) may be
    # replaced like a file this run created; the content check still holds
    # and the old version is saved first. A sidecar alone is not.
    created_by_run = created_by_run | {
        _sidecar_of(path) for status, path in changes if status[:1] in {"A", "M"}
    }
    applied: list[str] = []
    skipped: dict[str, str] = {}
    for status, path in changes:
        try:
            verdict = _classify_for_apply(
                repo, status, path, before, created_by_run, left_out
            )
            if verdict == "noop":
                applied.append(path)
            elif verdict == "delete":
                undo_backup.save_before_replace(repo, [path])
                (repo / path).unlink()
                run_checkpoint.note_written(repo, [path])
                applied.append(path)
            elif verdict == "write":
                content = _git_bytes(repo, "cat-file", "--filters", f"{after}:{path}")
                if content.returncode != 0:
                    skipped[path] = "git could not read the step's version of this file"
                    continue
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                undo_backup.save_before_replace(repo, [path])
                target.write_bytes(content.stdout)
                run_checkpoint.note_written(repo, [path])
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
    created = {path for status, path in changes if status.startswith("A")}
    return WorkingTreeApply(
        tuple(applied), skipped, patch_path, frozenset(created & set(applied))
    )


# ---------------------------------------------------------------------------
# Repository housekeeping (board S-016)
# ---------------------------------------------------------------------------

STEP_BRANCH_PREFIX = "rootact/step/"


def proposed_changes(
    repo: Path, before: str, after: str
) -> list[tuple[str, bytes | None, bytes | None]]:
    """Each path a step commit changes, with its blob bytes at *before* and *after*.

    The blobs are git's stored bytes (no smudge filter): what a review compares,
    and what ``reviewed_commit`` hashes back. ``.ract/`` is never listed.
    """
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
        raise WorktreeError(
            f"git could not list the step's changes: {listing.stderr.strip()}"
        )
    fields = [f for f in listing.stdout.split("\0") if f]
    out: list[tuple[str, bytes | None, bytes | None]] = []
    for status, path in zip(fields[0::2], fields[1::2]):

        def blob(commit: str, _path: str = path) -> bytes | None:
            shown = _git_bytes(repo, "cat-file", "blob", f"{commit}:{_path}")
            return shown.stdout if shown.returncode == 0 else None

        out.append(
            (
                path,
                None if status == "A" else blob(before),
                None if status == "D" else blob(after),
            )
        )
    return out


def reviewed_commit(repo: Path, after: str, kept: dict[str, bytes | None]) -> str:
    """A commit on top of *after* whose files are as the review kept them (D6).

    Built in a temporary index, so the operator's index is never touched. A
    path whose kept content is None is removed. Returns *after* itself when
    nothing differs.
    """
    import tempfile

    changed = {
        path: data
        for path, data in kept.items()
        if data != _git_bytes(repo, "cat-file", "blob", f"{after}:{path}").stdout
        or (data is None and _blob_in(repo, after, path) is not None)
    }
    if not changed:
        return after
    handle, index = tempfile.mkstemp(prefix="ract-review-index-")
    os.close(handle)
    env = ract_commit_env()
    env["GIT_INDEX_FILE"] = index
    try:

        def git(*args: str, data: bytes | None = None) -> str:
            done = subprocess.run(
                ["git", "-C", str(repo), *args],
                input=data,
                capture_output=True,
                env=env,
                check=False,
            )
            if done.returncode != 0:
                raise WorktreeError(
                    f"git {args[0]} failed while recording the review: "
                    f"{done.stderr.decode('utf-8', 'replace').strip()}"
                )
            return done.stdout.decode("utf-8", "replace").strip()

        git("read-tree", after)
        for path, data in changed.items():
            if data is None:
                git("update-index", "--force-remove", "--", path)
                continue
            sha = git("hash-object", "-w", "--no-filters", "--stdin", data=data)
            mode = "100644"
            listed = _git_in(repo, "ls-tree", after, "--", path).stdout.split()
            if listed:
                mode = listed[0]
            git("update-index", "--add", "--cacheinfo", f"{mode},{sha},{path}")
        tree = git("write-tree")
        return git(
            *_NO_SIGNING, "commit-tree", tree, "-p", after, "-m", "rootact reviewed"
        )
    finally:
        try:
            os.unlink(index)
        except OSError as exc:
            print(f"[worktree] temporary index not removed: {exc}", flush=True)


INIT_COMMAND = (
    "git init, then git add of the current files (sensitive files left out) "
    'and git commit -m "ract: initial commit of the current files"'
)


def init_preview(root: Path) -> tuple[int, list[str]]:
    """What ``init_repository`` would commit: the file count and the names left out.

    Read-only: walks the folder (no ``.git`` yet), skipping ``.ract/`` and
    secret-shaped names the way the base snapshot does.
    """
    count = 0
    left_out: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        name = path.relative_to(root).as_posix()
        if name.split("/", 1)[0] == ".git":
            continue
        if _is_snapshot_excluded(name):
            if name.split("/", 1)[0] != ".ract":
                left_out.append(name)
            continue
        count += 1
    return count, left_out


def init_repository(root: Path) -> list[str]:
    """``git init`` plus an initial commit of the current files; the names left out.

    LR:: ADR-0047 D6: offered as a tier-2 action when a step would change files
    in a folder that is not a repository, and run only on the operator's yes.
    Sensitive files (secret-shaped names, ``.ract/``) are not added, so they
    never reach a worktree; ``.gitignore`` is honored. RACT's identity, no
    operator hook, no signing. Raises ``WorktreeError`` when git fails.
    """
    done = _git_in(root, "init", "-q")
    if done.returncode != 0:
        raise WorktreeError(f"git init failed: {done.stderr.strip()}")
    names = _untracked_files(root)
    keep = [n for n in names if not _is_snapshot_excluded(n)]
    left_out = [
        n for n in names if _is_snapshot_excluded(n) and not n.startswith(".ract/")
    ]
    env = ract_commit_env()
    for start in range(0, len(keep), 200):
        added = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                *_no_hooks(),
                "add",
                "--",
                *keep[start : start + 200],
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if added.returncode != 0:
            raise WorktreeError(f"git add failed: {added.stderr.strip()}")
    committed = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            *_no_hooks(),
            *_NO_SIGNING,
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "ract: initial commit of the current files",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if committed.returncode != 0:
        raise WorktreeError(f"git commit failed: {committed.stderr.strip()}")
    return left_out


CHECKPOINT_REFS = "refs/ract/checkpoints"


def keep_checkpoint_ref(repo: Path, turn_id: str, n: int, commit: str) -> str | None:
    """Keep *commit* under ``refs/ract/checkpoints/<turn_id>/<n>``; the ref, or None.

    LR:: ADR-0047 D6: every apply records its base snapshot so ``git gc``
    keeps it; the snapshot is a commit nothing else points at. The turn id is
    the checkpoint ``/checkpoint`` and ``/restore`` name. No hook of the
    operator's runs (reference-transaction hooks included). A failure is
    printed and the apply stands: the files' own checkpoint is the turn's
    saved copies.
    """
    ref = f"{CHECKPOINT_REFS}/{turn_id}/{n}"
    done = _git_in(repo, *_no_hooks(), "update-ref", ref, commit)
    if done.returncode != 0:
        print(
            f"[worktree] checkpoint ref {ref} not kept: {done.stderr.strip()}",
            flush=True,
        )
        return None
    return ref


def drop_checkpoint_refs(repo: Path, turn_id: str) -> None:
    """Remove the refs of checkpoint *turn_id* (its turn folder was pruned)."""
    listing = _git_in(
        repo, "for-each-ref", "--format=%(refname)", f"{CHECKPOINT_REFS}/{turn_id}/"
    )
    if listing.returncode != 0:
        print(
            f"[worktree] checkpoint refs of {turn_id} not listed: {listing.stderr.strip()}",
            flush=True,
        )
        return
    for ref in listing.stdout.split():
        gone = _git_in(repo, *_no_hooks(), "update-ref", "-d", ref)
        if gone.returncode != 0:
            print(f"[worktree] {ref} not removed: {gone.stderr.strip()}", flush=True)


def repo_root_commit(repo: Path) -> str | None:
    """The first commit of the repository at *repo* (the lowest when several), or None.

    A tier-3 grant may bind to it (ADR-0048 D3), so a policy copied into
    another repository does not hold there.
    """
    done = _git_in(repo, "rev-list", "--max-parents=0", "HEAD")
    if done.returncode != 0:
        return None
    roots = sorted(done.stdout.split())
    return roots[0] if roots else None


# ---------------------------------------------------------------------------
# Step worktrees no live process owns (B-146)
# ---------------------------------------------------------------------------

OWNER_SUFFIX = ".owner"


def _owner_path(worktree: Path) -> Path:
    return worktree.with_name(worktree.name + OWNER_SUFFIX)


def _write_owner(worktree: Path) -> None:
    """Record which process made *worktree* (pid and its start time), beside it."""
    import json

    from ract.executor.process_identity import capture_identity

    identity = capture_identity(os.getpid())
    data = {"pid": os.getpid(), "created": identity.creation_time_ns if identity else 0}
    try:
        _owner_path(worktree).write_text(json.dumps(data), encoding="utf-8")
    except OSError as exc:
        print(
            f"[worktree] the owner of {worktree.name} was not recorded: {exc}",
            flush=True,
        )


def _owner_alive(worktree: Path) -> bool:
    """True while the process that made *worktree* runs (the same pid and start time)."""
    import json

    from ract.executor.process_identity import (
        ProcessIdentity,
        current_identity,
        same_process,
    )

    try:
        data = json.loads(_owner_path(worktree).read_text(encoding="utf-8"))
        stored = ProcessIdentity(int(data["pid"]), int(data["created"]))
    except (OSError, ValueError, KeyError, TypeError):
        return False  # no readable owner: nothing alive vouches for it
    return same_process(stored, current_identity(stored.pid)) and _running(stored.pid)


def _running(pid: int) -> bool:
    """True while *pid* runs: an exited process that is still held open (Windows)
    or not yet reaped (a zombie) keeps its identity, and owns nothing."""
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    # The state field follows the command name in parentheses.
    return stat.rsplit(")", 1)[-1].split()[:1] != ["Z"]


def _registered(repo: Path) -> list[Path]:
    """The worktree paths git has registered for *repo* (the main one left out)."""
    done = _git_in(repo, "worktree", "list", "--porcelain")
    if done.returncode != 0:
        return []
    paths = [
        Path(line[len("worktree ") :])
        for line in done.stdout.splitlines()
        if line.startswith("worktree ")
    ]
    return paths[1:]


def sweep_orphan_worktrees(repo: Path) -> list[str]:
    """Remove step worktrees RACT made that no live process owns; their names.

    LR:: B-146: a process that ended (killed, or quit before an interrupted
    step finished its cleanup) left its step worktree registered in the
    operator's repository. Only worktrees under ``.git/ract-worktrees`` are
    touched, never one the operator made, and never one whose owner runs.
    """
    root = Path(os.path.realpath(Path(repo) / ".git" / "ract-worktrees"))
    removed: list[str] = []
    for path in _registered(Path(repo)):
        real = Path(os.path.realpath(path))
        if real.parent != root or _owner_alive(real):
            continue
        done = _git_in(repo, "worktree", "remove", "--force", str(real))
        if done.returncode != 0 and real.exists():
            print(
                f"[worktree] {real.name} was not removed: {done.stderr.strip()}",
                flush=True,
            )
            continue
        # B-146: a registration whose folder is gone is pruned below.
        try:
            _owner_path(real).unlink(missing_ok=True)
        except OSError as exc:
            print(f"[worktree] the owner file of {real.name} stays: {exc}", flush=True)
        removed.append(real.name)
    if removed:
        _git_in(repo, "worktree", "prune")
    return removed


def remove_own_worktrees(repo: Path) -> list[str]:
    """Remove the step worktrees this process made; for the session's end (B-146).

    LR:: Called only when no turn's worker is still running, so none of them
    is in use. On Linux the interrupted step's cleanup could leave its
    worktree registered (a git it ran was cut short by the same Ctrl-C);
    the session ended with it listed in the operator's repository.
    """
    import json

    root = Path(os.path.realpath(Path(repo) / ".git" / "ract-worktrees"))
    removed: list[str] = []
    for path in _registered(Path(repo)):
        real = Path(os.path.realpath(path))
        if real.parent != root:
            continue
        try:
            owner = json.loads(_owner_path(real).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # no record of who made it: the next session's sweep decides
        if owner.get("pid") != os.getpid():
            continue
        done = _git_in(repo, "worktree", "remove", "--force", str(real))
        if done.returncode != 0 and real.exists():
            print(f"[worktree] {real.name} stays: {done.stderr.strip()}", flush=True)
            continue
        try:
            _owner_path(real).unlink(missing_ok=True)
        except OSError as exc:
            print(f"[worktree] the owner file of {real.name} stays: {exc}", flush=True)
        removed.append(real.name)
    if removed:
        _git_in(repo, "worktree", "prune")
    return removed


def ensure_ract_dir_excluded(repo: Path) -> bool:
    """Add ``.ract/`` to the repository's local exclude file, once.

    LR:: RACT keeps its state in ``.ract/``, which showed up as untracked in
    every ``git status``. ``.git/info/exclude`` is local to this clone and is
    never committed, so the operator's ``.gitignore`` is left alone. RACT
    itself writes this one line; model tools may never write under ``.git``
    (ADR-0047 D3). The path comes from ``git rev-parse --git-path`` so a
    linked worktree, whose ``.git`` is a file, is handled.

    Returns True when the line was added, False when it was already there or
    ``repo`` is not a git repository. Checked once per repository per process:
    an interactive session runs it on its first turn only (B-036).
    """
    key = str(Path(repo).resolve())
    if key in _EXCLUDE_CHECKED:
        return False
    found = _git_in(repo, "rev-parse", "--git-path", "info/exclude")
    if found.returncode != 0 or not found.stdout.strip():
        return False
    exclude = Path(found.stdout.strip())
    if not exclude.is_absolute():
        exclude = Path(repo) / exclude
    existing = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    _EXCLUDE_CHECKED.add(key)
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


# Repositories whose exclude file this process has already checked.
_EXCLUDE_CHECKED: set[str] = set()


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


def current_branch(repo: Path) -> str | None:
    """Name of the checked-out branch, or None (not a repo, detached HEAD)."""
    result = _git_in(repo, "branch", "--show-current")
    name = result.stdout.strip()
    return name if result.returncode == 0 and name else None


def working_tree_status(repo: Path) -> dict[str, str] | None:
    """Map of path to a change signature for changed and untracked files.

    The signature is the porcelain status plus the file's size and mtime.
    LR:: Status letters alone are not enough: since each run starts from a
    snapshot of the working tree (S-011b), a dirty tree is normal, and a
    second edit to a file that is already modified keeps the same ` M`. With
    size and mtime in the signature that edit shows as a change.

    None when ``repo`` is not inside a git work tree. Used by the session to
    say which files a turn changed (compare before and after).
    """
    inside = _git_in(repo, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return None
    listing = _git_in(repo, "status", "--porcelain", "-z", "--untracked-files=all")
    entries: dict[str, str] = {}
    fields = listing.stdout.split("\0")
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        if status[0] in {"R", "C"}:
            i += 1  # the source path of a rename or copy follows
        try:
            st = (Path(repo) / path).stat()
            entries[path] = f"{status}|{st.st_size}|{st.st_mtime_ns}"
        except OSError:
            entries[path] = f"{status}|missing"
    return entries


# RACT 0.4.0
