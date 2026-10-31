"""Slice (d): allowlist mode, session approvals, changed entry points (B-113, ADR-0048 D4, D6).

LR:: In ``allowlist`` mode a command that matches an allow rule runs without
asking. Three things still ask, in every mode: what the matcher asks about
(the always-ask list: remote git, output and execution flags, a file
written in this session named in the arguments); tier 2; and a changed
repository-defined entry point (G-214): a test, conftest or runner
configuration file the model wrote in this session, or any such file whose
content changed since the grant was signed. An allow rule does not answer
for those, because they decide what the allowed command does.

"Changed since the grant was signed" needs what the files were at signing:
``record_signed`` keeps their digests in the user state folder (never in the
project, which a repository could ship), keyed by the grant's digest. A
grant with no record (signed before this release, or on another machine)
counts every entry point as changed: it asks.

Session approvals are the operator's "for this session" answer: the exact
argv runs without asking again until the session ends. They live in memory
only and never carry over to ``/resume``.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from ract import programs

# Files a test runner executes or reads as configuration (G-214 T2).
# Files a test runner or a verifier executes or reads as configuration: the
# runners' own files, the build and lint tools' files (B-023), and anything
# the review named (pytest reads .pytest.ini first; a Makefile is what an
# allowed make runs).
RUNNER_FILES = frozenset(
    {
        "conftest.py",
        "pytest.ini",
        ".pytest.ini",
        "pytest.toml",
        "pyproject.toml",
        "tox.ini",
        "setup.cfg",
        "setup.py",
        "noxfile.py",
        "mypy.ini",
        ".mypy.ini",
        ".flake8",
        "ruff.toml",
        ".ruff.toml",
        "Makefile",
        "makefile",
        "GNUmakefile",
        "Cargo.toml",
        "build.rs",
        "package.json",
        "tsconfig.json",
    }
)
# Configuration whose name is a family: jest.config.js, eslint.config.mjs,
# .eslintrc.cjs, vitest.config.ts, prettier.config.js and the rest.
_CONFIG_PREFIXES = (
    "jest.config.",
    "vitest.config.",
    "eslint.config.",
    ".eslintrc",
    "prettier.config.",
    ".prettierrc",
    "babel.config.",
    ".babelrc",
)
# JavaScript and TypeScript test files (``is_test_file`` knows Python only).
_JS_TEST = (".test.", ".spec.")
_JS_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
LINKED = "a link: what it points at decides what runs"
WRITTEN = "written by the model this session"
CHANGED = "changed since the grant was signed"
UNKNOWN = "the project's entry points could not be listed"
NAMED_UNCOVERED = "named by the command, in a folder the signed record does not cover"
# Folders pytest does not collect from by default (its norecursedirs, and
# every folder whose name starts with a dot): their test files are not
# entry points of this project's runner. A config that changes that is
# itself an entry point, so a change to it asks.
_NOT_COLLECTED = frozenset(
    {
        "node_modules",
        "venv",
        "build",
        "dist",
        "site-packages",
        "__pycache__",
        "_darcs",
        "CVS",
    }
)


def _collected(rel: str) -> bool:
    folders = Path(rel).parts[:-1]
    return not any(
        part.startswith(".") or part in _NOT_COLLECTED or part.endswith(".egg")
        for part in folders
    )


def is_entry_point(path: str) -> bool:
    """A test, conftest, runner or verifier configuration file, or a Python
    file at the top of the project (``python -m`` puts the working folder
    first on sys.path, so a top-level ``pytest.py`` would shadow the runner)."""
    from ract.import_check import is_test_file

    p = Path(path.replace("\\", "/"))
    name = p.name
    if name in RUNNER_FILES or name.startswith(_CONFIG_PREFIXES) or is_test_file(path):
        return True
    if len(p.parts) == 1 and name.endswith(".py"):
        return True
    if name.endswith(_JS_SUFFIXES) and (
        any(mark in name for mark in _JS_TEST) or "__tests__" in p.parts
    ):
        return True
    return False


# B-148: bounds on the work at run entry. Past any of them the record is
# unknown, so every command asks (the safe answer), and the turn says so.
MAX_ENTRY_POINTS = 5000
MAX_ENTRY_BYTES = 64 * 1024 * 1024
ENTRY_DEADLINE_S = 10.0


def _bound_hit(what: str) -> None:
    from ract import turn_context

    text = (
        f"the project's entry points were not all read ({what}); every tier-3 "
        "command asks this turn"
    )
    print(f"[allowlist] {text}", flush=True)
    if turn_context.has_reporter():
        turn_context.report("notice", {"level": "warning", "text": text})


def entry_point_digests(project: Path | str) -> dict[str, str] | None:
    """The SHA-256 of every entry point in *project*, tracked, new or ignored (B-027:
    a planted conftest.py counts even when the repository's .gitignore hides it)."""
    project = Path(project)
    try:
        done = subprocess.run(
            # core.fsmonitor=false: a repository's config cannot start a program.
            [
                programs.git(),
                "-c",
                "core.fsmonitor=false",
                "ls-files",
                "-z",
                "--cached",
                "--others",
            ],
            cwd=project,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[allowlist] the project's files were not listed: {exc}", flush=True)
        return None
    if done.returncode != 0:
        # Not a git repository, or git refused: the entry points are unknown.
        return None
    digests: dict[str, str] = {}
    read_bytes = 0
    deadline = time.monotonic() + ENTRY_DEADLINE_S
    for raw in done.stdout.split(b"\0"):
        rel = raw.decode("utf-8", errors="replace")
        if not rel or not is_entry_point(rel) or not _collected(rel):
            continue
        if len(digests) >= MAX_ENTRY_POINTS:
            _bound_hit(f"more than {MAX_ENTRY_POINTS} entry points")
            return None
        if time.monotonic() > deadline:
            _bound_hit(f"reading them took over {ENTRY_DEADLINE_S:g} s")
            return None
        path = project / rel
        try:
            if path.is_symlink():
                # The target can change without the link changing: a linked
                # entry point is never taken as unchanged.
                digests[rel] = LINKED
                continue
            if not path.is_file():
                continue
            size = path.stat().st_size
            if read_bytes + size > MAX_ENTRY_BYTES:
                _bound_hit(f"more than {MAX_ENTRY_BYTES // (1024 * 1024)} MiB of them")
                return None
            read_bytes += size
            digests[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            print(f"[allowlist] {rel} was not read: {exc}", flush=True)
    return digests


def _record_path(project: Path | str, grant_digest: str) -> Path:
    from ract.key_paths import repo_key_dir

    return repo_key_dir(project, "grants") / f"{grant_digest}.entrypoints.json"


def record_signed(project: Path | str, grant_digest: str) -> None:
    """Keep what the entry points were when this grant was signed (canonical JSON)."""
    from ract.canonical import dumps_jcs

    path = _record_path(project, grant_digest)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        digests = entry_point_digests(project)
        if digests is None:
            # Nothing to compare with later: every entry point then counts as changed.
            return
        temp.write_text(dumps_jcs(digests).decode("utf-8"), encoding="utf-8")
        os.replace(temp, path)
    except OSError as exc:
        print(f"[allowlist] the entry points were not recorded: {exc}", flush=True)


def _signed_digests(
    project: Path | str, grant_digest: str | None
) -> dict[str, str] | None:
    if not grant_digest:
        return None
    path = _record_path(project, grant_digest)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        print(f"[allowlist] the entry-point record cannot be read: {exc}", flush=True)
        return None
    return data if isinstance(data, dict) else None


@dataclass(frozen=True)
class Change:
    path: str
    reason: str


def _named_uncovered(argv: list[str] | tuple[str, ...]) -> list[str]:
    """The paths *argv* names inside folders the record leaves out (G-237 L1).

    pytest collects a path named on its command line from any folder, so a
    planted ``.hidden/test_x.py`` or ``build/conftest.py`` named as a
    selector would run; the record skips those folders, so it cannot vouch
    for them, and the command asks.
    """
    found = []
    for token in list(argv)[1:]:
        if not token or token.startswith("-"):
            continue
        rel = token.split("::", 1)[0].replace("\\", "/").strip("/")
        if rel and not _collected(rel + "/x"):
            found.append(rel)
    return found


def changed_entry_points(
    project: Path | str,
    grant_digest: str | None,
    model_written: set[str] | frozenset[str],
    *,
    record_project: Path | str | None = None,
    argv: list[str] | tuple[str, ...] = (),
) -> list[Change]:
    """The entry points that put a command back to the question, each with why."""
    changes = [
        Change(path, WRITTEN) for path in sorted(model_written) if is_entry_point(path)
    ]
    changes += [Change(path, NAMED_UNCOVERED) for path in _named_uncovered(argv)]
    shown = {c.path for c in changes}
    # The record is kept per operator project; the files are read in *project*,
    # the folder the command runs in (the step worktree, a copy of it).
    signed = _signed_digests(record_project or project, grant_digest)
    now = entry_point_digests(project)
    if now is None:
        # Not knowing what would run is not a match: it asks.
        return [*changes, Change(".", UNKNOWN)]
    if signed is None:
        # No record of this grant's signing: every entry point counts as changed.
        return changes + [Change(p, CHANGED) for p in sorted(now) if p not in shown]
    for path in sorted(set(now) | set(signed)):
        if path in shown:
            continue
        if now.get(path) == LINKED:
            changes.append(Change(path, LINKED))
        elif now.get(path) != signed.get(path):
            changes.append(Change(path, CHANGED))
    return changes


@dataclass
class SessionApprovals:
    """The exact argvs the operator approved for this session (memory only)."""

    approved: set[tuple[str, ...]] = field(default_factory=set)

    def covers(self, argv: list[str] | tuple[str, ...]) -> bool:
        return tuple(argv) in self.approved

    def add(self, argv: list[str] | tuple[str, ...]) -> None:
        self.approved.add(tuple(argv))

    def listed(self) -> list[tuple[str, ...]]:
        return sorted(self.approved)


__all__ = [
    "CHANGED",
    "Change",
    "RUNNER_FILES",
    "SessionApprovals",
    "WRITTEN",
    "changed_entry_points",
    "entry_point_digests",
    "is_entry_point",
    "record_signed",
]
