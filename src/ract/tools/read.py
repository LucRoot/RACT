"""The read-only tools: ``read_file``, ``list_dir``, ``glob`` and ``grep`` (B-010a).

LR:: Every path a model names goes through ``resolve_workspace_path`` (the one
resolver, S-001), and is checked again after links are followed: it must still
sit inside the project, and the never-sent rule (``is_never_sent``: .git,
.ract, secret-shaped names, RACT's own config) applies to where it really
points. Walks never enter .git, .ract or a link or junction, and skip
gitignored paths unless the call asks for them. ``grep`` runs ripgrep found on
PATH outside the project (a repository can ship an ``rg.exe`` that Windows would
otherwise find in the working folder), with a fixed argv, a scrubbed
environment and a timeout; without ripgrep a child Python does the search and
is killed at the same timeout, so a catastrophic regex cannot hang the session.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ract.core.threat_model import CapabilityTier
from ract.tools import ToolRefused, ToolResult, ToolSpec
from ract.workspace_path import is_never_sent, resolve_workspace_path

READ_CAP_BYTES = 256 * 1024
MAX_READ_FILE_BYTES = 64 * 1024 * 1024
DEFAULT_LINES = 2000
MAX_ENTRIES = 1000
MAX_MATCHES = 200
MAX_GREP_FILE_BYTES = 8 * 1024 * 1024
GREP_TIMEOUT_SECONDS = 10.0
_BINARY_PROBE = 8192
_NEVER = (
    "RACT never sends .git, .ract, secret-shaped files or its own config to a model"
)


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadFileArgs(_Args):
    path: str = Field(min_length=1, max_length=4096)
    offset: int | None = Field(default=None, ge=1)
    limit: int | None = Field(default=None, ge=1, le=10_000)


class ListDirArgs(_Args):
    path: str = Field(default=".", min_length=1, max_length=4096)
    include_ignored: bool = False


class GlobArgs(_Args):
    pattern: str = Field(min_length=1, max_length=500)
    include_ignored: bool = False


class GrepArgs(_Args):
    pattern: str = Field(min_length=1, max_length=1000)
    path: str = Field(default=".", min_length=1, max_length=4096)
    glob: str | None = Field(default=None, max_length=500)
    ignore_case: bool = False
    include_ignored: bool = False


# ------------------------------------------------------------------ paths


def _base(root: Path) -> Path:
    return Path(os.path.realpath(root))


def _inside(base: Path, path: Path) -> bool:
    real = os.path.normcase(os.path.realpath(path))
    top = os.path.normcase(str(base))
    try:
        return os.path.commonpath([top, real]) == top
    except ValueError:
        return False  # another drive


def _is_link(path: Path) -> bool:
    """A symlink or a Windows junction (``os.walk`` on 3.11 follows junctions)."""
    if path.is_symlink():
        return True
    return os.path.normcase(os.path.realpath(path)) != os.path.normcase(
        os.path.abspath(path)
    )


def _rel(base: Path, path: Path) -> str:
    rel = Path(os.path.realpath(path)).relative_to(base).as_posix()
    return rel or "."


def _resolve(root: Path, raw: str) -> tuple[Path, str]:
    """The real path *raw* names inside the project, and its relative form."""
    base = _base(root)
    if raw.strip().replace("\\", "/").rstrip("/") in ("", "."):
        return base, "."  # the project root: a folder the walks may start from
    resolved = resolve_workspace_path(base, raw, purpose="read")
    if not resolved.is_ok():
        raise ToolRefused(
            resolved.error or "the path is refused",
            resolved.hint or "use a path inside the project",
        )
    target = resolved.unwrap()
    if not _inside(base, target):
        raise ToolRefused(
            f"{raw!r} leads out of the project through a link",
            "use a path inside the project",
        )
    rel = _rel(base, target) if target.exists() else Path(raw).as_posix()
    if rel != "." and (is_never_sent(rel) or is_never_sent(raw)):
        raise ToolRefused(f"{rel} is not read: {_NEVER}", "read another file")
    if not target.exists():
        raise ToolRefused(f"{rel} does not exist", "list_dir shows what is there")
    return Path(os.path.realpath(target)), rel


def _git_ignored(base: Path, rels: list[str]) -> set[str]:
    """The paths among *rels* that git ignores; empty outside a repository."""
    if not rels:
        return set()
    try:
        done = subprocess.run(
            # core.fsmonitor=false: a repository's config cannot start a program.
            ["git", "-c", "core.fsmonitor=false", "check-ignore", "-z", "--stdin"],
            cwd=base,
            input="\0".join(rels) + "\0",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GREP_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if done.returncode not in (0, 1):
        return set()  # not a repository, or git refused: nothing is filtered
    return {p for p in done.stdout.split("\0") if p}


def _walk(base: Path, start: Path, include_ignored: bool) -> list[str]:
    """Every file under *start*, relative to *base*, in a stable order."""
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
        here = Path(dirpath)
        keep = []
        for name in sorted(dirnames):
            child = here / name
            if _is_link(child):
                continue
            if is_never_sent(child.relative_to(base).as_posix()):
                continue
            keep.append(name)
        dirnames[:] = keep
        for name in sorted(filenames):
            child = here / name
            rel = child.relative_to(base).as_posix()
            if _is_link(child) or is_never_sent(rel):
                continue
            files.append(rel)
        if len(files) > 50 * MAX_ENTRIES:
            break
    if not include_ignored:
        ignored = _git_ignored(base, files)
        files = [f for f in files if f not in ignored]
    return files


# ------------------------------------------------------------------ read_file


def _line_endings(data: bytes) -> str:
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    cr = data.count(b"\r") - crlf
    kinds = [name for name, n in (("crlf", crlf), ("lf", lf), ("cr", cr)) if n]
    if not kinds:
        return "none"
    return kinds[0] if len(kinds) == 1 else "mixed"


def read_file(root: Path, args: ReadFileArgs) -> ToolResult:
    full, rel = _resolve(root, args.path)
    if full.is_dir():
        raise ToolRefused(f"{rel} is a folder", "use list_dir for a folder")
    if not full.is_file():
        raise ToolRefused(f"{rel} is not a regular file", "read a regular file")
    size = full.stat().st_size
    if size > MAX_READ_FILE_BYTES:
        raise ToolRefused(
            f"{rel} is {size / 2**20:.0f} MiB; read_file reads files up to "
            f"{MAX_READ_FILE_BYTES // 2**20} MiB",
            "use grep to find the part you need",
        )
    data = full.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if b"\0" in data[:_BINARY_PROBE]:
        return ToolResult(
            text=f"{rel}: binary file, {size} bytes, sha256 {digest}",
            facts={"path": rel, "binary": True, "size": size, "sha256": digest},
        )
    try:
        text = data.decode("utf-8")
        utf8 = True
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
        utf8 = False
    bom = data.startswith(b"\xef\xbb\xbf")
    lines = text.lstrip(chr(0xFEFF)).splitlines()
    total = len(lines)
    start = args.offset or 1
    count = args.limit or DEFAULT_LINES
    shown = lines[start - 1 : start - 1 + count]
    end = start + len(shown) - 1
    facts = {
        "path": rel,
        "binary": False,
        "size": size,
        "sha256": digest,
        "lines": total,
        "utf8": utf8,
        "bom": bom,
        "line_endings": _line_endings(data),
        "first_line": start,
        "last_line": end,
    }
    note = (
        ""
        if utf8
        else " (not UTF-8: bytes that do not decode show as replacement characters)"
    )
    header = f"{rel}: lines {start}-{end} of {total}, sha256 {digest}{note}"
    body = "\n".join(f"{start + i:6}\t{line}" for i, line in enumerate(shown))
    return ToolResult(
        text=f"{header}\n{body}" if body else header,
        facts=facts,
        truncated=start > 1 or end < total,
    )


# ------------------------------------------------------------------ list_dir and glob


def list_dir(root: Path, args: ListDirArgs) -> ToolResult:
    full, rel = _resolve(root, args.path)
    if not full.is_dir():
        raise ToolRefused(f"{rel} is not a folder", "use read_file for a file")
    base = _base(root)
    entries: list[dict[str, Any]] = []
    for child in sorted(full.iterdir(), key=lambda p: p.name.casefold()):
        child_rel = child.relative_to(base).as_posix()
        if is_never_sent(child_rel):
            continue
        if _is_link(child):
            entries.append({"name": child.name, "kind": "link", "size": None})
        elif child.is_dir():
            entries.append({"name": child.name, "kind": "dir", "size": None})
        else:
            entries.append(
                {"name": child.name, "kind": "file", "size": child.stat().st_size}
            )
    if not args.include_ignored:
        prefix = "" if rel == "." else f"{rel}/"
        ignored = _git_ignored(base, [prefix + e["name"] for e in entries])
        entries = [e for e in entries if prefix + e["name"] not in ignored]
    cut = len(entries) > MAX_ENTRIES
    entries = entries[:MAX_ENTRIES]
    lines = [
        f"{e['name']}/"
        if e["kind"] == "dir"
        else (
            f"{e['name']} (link, not followed)"
            if e["kind"] == "link"
            else f"{e['name']} ({e['size']} bytes)"
        )
        for e in entries
    ]
    return ToolResult(
        text=f"{rel}: {len(entries)} entries\n" + "\n".join(lines),
        facts={"path": rel, "entries": entries},
        truncated=cut,
    )


def _glob_regex(pattern: str) -> re.Pattern[str]:
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    flags = re.IGNORECASE if os.name == "nt" else 0
    return re.compile("".join(out), flags)


def glob(root: Path, args: GlobArgs) -> ToolResult:
    base = _base(root)
    matcher = _glob_regex(args.pattern.replace("\\", "/").lstrip("./"))
    found = [
        rel for rel in _walk(base, base, args.include_ignored) if matcher.fullmatch(rel)
    ]
    cut = len(found) > MAX_ENTRIES
    found = found[:MAX_ENTRIES]
    return ToolResult(
        text=f"{len(found)} paths match {args.pattern}\n" + "\n".join(found),
        facts={"pattern": args.pattern, "paths": found},
        truncated=cut,
    )


# ------------------------------------------------------------------ grep


def _ripgrep(root: Path) -> str | None:
    """ripgrep's absolute path from PATH, never a program inside the project."""
    base = _base(root)
    name = "rg.exe" if os.name == "nt" else "rg"
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        if not folder or not os.path.isabs(folder):
            continue  # a relative entry would search the working folder
        candidate = Path(folder) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            if _inside(base, candidate):
                continue
            return os.path.realpath(candidate)
    return None


def _scrubbed_env(program: str) -> dict[str, str]:
    env = {"PATH": os.path.dirname(program)}
    for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
        if os.environ.get(name):
            env[name] = os.environ[name]
    return env


def _keep_match(base: Path, rel: str) -> bool:
    return not is_never_sent(rel) and _inside(base, base / rel)


def _grep_ripgrep(
    program: str, base: Path, rel: str, args: GrepArgs
) -> list[dict[str, Any]]:
    argv = [
        program,
        "--no-config",
        "--json",
        "--hidden",
        "--max-columns",
        "500",
        "--max-count",
        str(MAX_MATCHES),
        "--max-filesize",
        f"{MAX_GREP_FILE_BYTES // 2**20}M",
        "--glob",
        "!.git",
        "--glob",
        "!.ract",
    ]
    if args.include_ignored:
        argv.append("--no-ignore")
    if args.ignore_case:
        argv.append("--ignore-case")
    if args.glob:
        argv += ["--glob", args.glob]
    argv += ["-e", args.pattern, "--", rel]
    try:
        done = subprocess.run(
            argv,
            cwd=base,
            env=_scrubbed_env(program),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GREP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise ToolRefused(
            f"the search took longer than {GREP_TIMEOUT_SECONDS:.0f} s and was stopped",
            "use a narrower pattern or path",
        ) from None
    if done.returncode == 2 and not done.stdout:
        first = (done.stderr.strip().splitlines() or ["ripgrep refused the pattern"])[0]
        raise ToolRefused(
            f"the pattern was refused: {first}", "fix the regular expression"
        )
    matches: list[dict[str, Any]] = []
    for line in done.stdout.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("type") != "match":
            continue
        data = record.get("data") or {}
        path = ((data.get("path") or {}).get("text") or "").replace("\\", "/")
        path = path[2:] if path.startswith("./") else path
        text = ((data.get("lines") or {}).get("text") or "").rstrip("\r\n")
        if not path or not _keep_match(base, path):
            continue
        matches.append({"path": path, "line": data.get("line_number"), "text": text})
    return matches


_FALLBACK = r"""
import json, re, sys
job = json.loads(sys.stdin.read())
flags = re.IGNORECASE if job["ignore_case"] else 0
try:
    rx = re.compile(job["pattern"], flags)
except re.error as exc:
    print(json.dumps({"error": str(exc)})); sys.exit(0)
out = []
for rel in job["files"]:
    try:
        with open(job["base"] + "/" + rel, "rb") as fh:
            data = fh.read(job["max_bytes"] + 1)
    except OSError:
        continue
    if len(data) > job["max_bytes"] or b"\0" in data[:8192]:
        continue
    for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
        if rx.search(line):
            out.append({"path": rel, "line": n, "text": line[:500]})
            if len(out) >= job["max_matches"]:
                break
    if len(out) >= job["max_matches"]:
        break
print(json.dumps({"matches": out}))
"""


def _grep_python(base: Path, full: Path, args: GrepArgs) -> list[dict[str, Any]]:
    if full.is_file():
        rel = full.relative_to(base).as_posix()
        files = [] if is_never_sent(rel) else [rel]
    else:
        files = _walk(base, full, args.include_ignored)
    if args.glob:
        matcher = _glob_regex(args.glob)
        files = [
            f
            for f in files
            if matcher.fullmatch(f) or matcher.fullmatch(f.rsplit("/", 1)[-1])
        ]
    job = {
        "base": str(base),
        "files": files,
        "pattern": args.pattern,
        "ignore_case": args.ignore_case,
        "max_bytes": MAX_GREP_FILE_BYTES,
        "max_matches": MAX_MATCHES,
    }
    try:
        done = subprocess.run(
            [sys.executable, "-I", "-c", _FALLBACK],
            input=json.dumps(job),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GREP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise ToolRefused(
            f"the search took longer than {GREP_TIMEOUT_SECONDS:.0f} s and was stopped",
            "use a simpler pattern or a narrower path",
        ) from None
    try:
        reply = json.loads(done.stdout or "{}")
    except ValueError:
        reply = {}
    if "error" in reply:
        raise ToolRefused(
            f"the pattern was refused: {reply['error']}", "fix the regular expression"
        )
    return [m for m in reply.get("matches", []) if _keep_match(base, m["path"])]


def grep(root: Path, args: GrepArgs) -> ToolResult:
    full, rel = _resolve(root, args.path)
    base = _base(root)
    program = _ripgrep(base)
    if program is not None:
        matches = _grep_ripgrep(program, base, rel, args)
        engine = "ripgrep"
    else:
        matches = _grep_python(base, full, args)
        engine = "python"
    matches.sort(key=lambda m: (m["path"], m["line"] or 0))
    cut = len(matches) >= MAX_MATCHES
    matches = matches[:MAX_MATCHES]
    lines = [f"{m['path']}:{m['line']}: {m['text']}" for m in matches]
    return ToolResult(
        text=f"{len(matches)} matches for {args.pattern!r}\n" + "\n".join(lines),
        facts={"pattern": args.pattern, "matches": matches, "engine": engine},
        truncated=cut,
    )


# ------------------------------------------------------------------ the specs

# Registered by ``ract.tools`` (the package owns the registry).
READ_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "read_file",
        CapabilityTier.TIER_0_READ,
        ReadFileArgs,
        False,
        READ_CAP_BYTES,
        read_file,
    ),
    ToolSpec(
        "list_dir",
        CapabilityTier.TIER_0_READ,
        ListDirArgs,
        False,
        READ_CAP_BYTES,
        list_dir,
    ),
    ToolSpec("glob", CapabilityTier.TIER_0_READ, GlobArgs, False, READ_CAP_BYTES, glob),
    ToolSpec("grep", CapabilityTier.TIER_0_READ, GrepArgs, False, READ_CAP_BYTES, grep),
)
