"""Source-tree golden hash — one scalar over the shipped surface.

Any change to ``src/ract`` under an included suffix flips the scalar
and forces a conscious re-lock. Docs, tests, ``_BUILD/`` scratch, and
compiled caches sit outside the tracked surface, so unrelated edits
do not disturb the hash.

The locked value lives in :data:`GOLDEN_HASH_CONSTANT`. Update it
through the ``ract source-digest --lock`` CLI verb rather than by hand;
the CLI rewrites this file in place.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


# Roots of the tracked surface, expressed as POSIX paths relative to
# the repository root.
TRACKED_ROOTS: tuple[str, ...] = ("src/ract",)

# File suffixes that participate in the digest. Kept narrow so a stray
# ``.pyc`` or a build artifact cannot flip the hash, but wide enough to
# cover every packaged surface (packaged prompt text, type stubs,
# config-like data files under ``src/ract``).
INCLUDED_SUFFIXES: tuple[str, ...] = (
    ".py",
    ".pyi",
    ".json",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
)

# Directory names skipped anywhere in the tree.
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset({"__pycache__"})


# Regex bound to a start-of-line ``GOLDEN_HASH_CONSTANT`` assignment.
# The self-hash substitution and the ``--lock`` rewrite both use this
# so an unrelated byte-string literal that happens to contain the
# constant name cannot be matched by accident.
_HASH_ASSIGNMENT_RE = re.compile(
    r'^GOLDEN_HASH_CONSTANT: str = "([0-9a-f]{64})"',
    re.MULTILINE,
)
_HASH_ASSIGNMENT_RE_BYTES = re.compile(
    rb'^GOLDEN_HASH_CONSTANT: str = "([0-9a-f]{64})"',
    re.MULTILINE,
)

# Placeholder written in place of the pinned hash when computing this
# file's content digest. Without the substitution, ``source_digest.py``
# would depend on its own hash, so every ``--lock`` op would flip the
# hash away from the just-locked value. With the substitution, the
# rest of the file (TRACKED_ROOTS, INCLUDED_SUFFIXES, the hash logic
# itself) is still covered.
_SELF_HASH_PLACEHOLDER = b"<self-hash>"


def _repo_root() -> Path:
    """Return the repository root (three parents up from this file)."""
    return Path(__file__).resolve().parent.parent.parent


def _iter_tracked_files(repo_root: Path) -> list[Path]:
    """Return the sorted list of files that participate in the digest."""
    found: list[Path] = []
    for root in TRACKED_ROOTS:
        base = repo_root / root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in INCLUDED_SUFFIXES:
                continue
            if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
                continue
            found.append(path)
    found.sort()
    return found


def _content_bytes_for(path: Path, self_path: Path) -> bytes:
    """Return the bytes to hash for ``path``.

    For ``self_path`` (this module) the pinned hash value is replaced
    with :data:`_SELF_HASH_PLACEHOLDER` so the file's own
    ``GOLDEN_HASH_CONSTANT`` value does not participate.

    Line endings are normalized to LF before hashing so a Windows
    checkout (CRLF via ``core.autocrlf``) and a Linux checkout (LF)
    produce the same digest. Without this the golden-hash test flips
    across platforms even when the tracked content is identical.
    """
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    if path.resolve() != self_path:
        return raw
    return _HASH_ASSIGNMENT_RE_BYTES.sub(
        b'GOLDEN_HASH_CONSTANT: str = "' + _SELF_HASH_PLACEHOLDER + b'"',
        raw,
        count=1,
    )


def compute_golden_hash(repo_root: Path | None = None) -> str:
    """Compute the SHA-256 over sorted (path, sha256(content)) pairs.

    ``repo_root`` is resolved from :func:`_repo_root` when not given.
    Paths are recorded as POSIX-relative to the repo root so the digest
    is invariant across Windows and POSIX checkouts. This module's own
    ``GOLDEN_HASH_CONSTANT`` value is substituted with a placeholder
    while computing (see :data:`_SELF_HASH_PLACEHOLDER`).
    """
    root = (repo_root or _repo_root()).resolve()
    self_path = Path(__file__).resolve()
    hasher = hashlib.sha256()
    for path in _iter_tracked_files(root):
        content = _content_bytes_for(path, self_path)
        content_digest = hashlib.sha256(content).hexdigest()
        rel = path.resolve().relative_to(root).as_posix()
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(content_digest.encode("ascii"))
        hasher.update(b"\n")
    return hasher.hexdigest()


# The pinned value. Update through ``ract source-digest --lock``.
GOLDEN_HASH_CONSTANT: str = "b4c16fe52555ca877dc60c7cbbabe81e92f71a97745a86daaad8c5ab71ea45c7"  # fmt: skip


def rewrite_golden_hash_constant(new_hash: str) -> Path:
    """Rewrite the ``GOLDEN_HASH_CONSTANT`` assignment in this file.

    Returns the path of the file that was rewritten. Called by
    ``ract source-digest --lock``. Matches a start-of-line
    ``GOLDEN_HASH_CONSTANT`` assignment so an unrelated byte-string
    literal that contains the constant name is not disturbed.
    """
    if not re.fullmatch(r"[0-9a-f]{64}", new_hash):
        raise ValueError(f"new_hash is not a lowercase sha256 hex digest: {new_hash!r}")
    target = Path(__file__).resolve()
    text = target.read_text(encoding="utf-8")
    replacement = f'GOLDEN_HASH_CONSTANT: str = "{new_hash}"'
    new_text, n = _HASH_ASSIGNMENT_RE.subn(replacement, text, count=1)
    if n != 1:
        raise RuntimeError("GOLDEN_HASH_CONSTANT assignment not found")
    target.write_text(new_text, encoding="utf-8")
    return target
