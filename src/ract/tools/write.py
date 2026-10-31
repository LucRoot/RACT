"""The write tools and the repository map (ADR-0047 D1, D3, D4; B-110 D1).

LR:: A write tool changes files only inside the root it is given (the step
worktree, in the agent loop), only through the one path resolver, and only
on what the model has read: an existing file is changed only when the
caller passes the digest the file has now, so a model cannot overwrite what
it did not see. Writes land through a temporary file in the same directory
and ``os.replace``. A file that is not clean UTF-8 can be read and not
edited. Edits keep the file's byte order mark and its line ending style.

The tier of a call is the highest of the tool's declared tier and the tiers
of the paths it touches (D3): a control file or a file another program acts
on by itself is tier 2; ``.git``, ``.ract`` and the agent-configuration
directories of coding tools are refused for every tool. ``call_tier`` gives
that tier; the tier gate and the approvals are D6.
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ract import turn_context
from ract.core.threat_model import CapabilityTier
from ract.tools import ToolRefused, ToolResult, ToolSpec
from ract.workspace_path import require_workspace_path, WorkspacePathRefused

WRITE_CAP_BYTES = 16 * 1024
MAP_CAP_BYTES = 64 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
MAP_MAX_FILES = 2000
_BOM = b"\xef\xbb\xbf"

# D3: refused for every tool, at any depth. A fixed list, never narrowed.
AGENT_CONFIG_DIRS = frozenset(
    {".agents", ".claude", ".cursor", ".codex", ".continue", ".windsurf", ".aider"}
)
# D3: RACT control files (ract.yaml itself stays refused by the path resolver).
GUIDANCE_FILES = frozenset({"ract.md", "agents.md", "claude.md"})
# D3: files some program acts on by itself.
EXECUTABLE_CONFIG_GLOBS = (
    ".github/workflows/*",
    ".envrc",
    ".vscode/*",
    ".idea/*",
    ".devcontainer/*",
    ".pre-commit-config.yaml",
    ".husky/*",
    ".githooks/*",
    ".venv/*",
    "venv/*",
)


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WriteFileArgs(_Args):
    path: str = Field(min_length=1, max_length=4096)
    content: str = Field(max_length=MAX_FILE_BYTES)
    expected_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    create: bool = False


class EditFileArgs(_Args):
    path: str = Field(min_length=1, max_length=4096)
    old: str = Field(min_length=1, max_length=MAX_FILE_BYTES)
    new: str = Field(max_length=MAX_FILE_BYTES)
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    replace_all: bool = False


class DeleteFileArgs(_Args):
    path: str = Field(min_length=1, max_length=4096)
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class MoveFileArgs(_Args):
    path: str = Field(min_length=1, max_length=4096)
    destination: str = Field(min_length=1, max_length=4096)
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ApplyPatchArgs(_Args):
    patch: str = Field(min_length=1, max_length=MAX_FILE_BYTES)


class RepoMapArgs(_Args):
    path: str = Field(default=".", min_length=1, max_length=4096)
    include_ignored: bool = False


# ------------------------------------------------------------------ tiers


def _prompts_dir(root: Path) -> str:
    """The configured ``prompts_dir`` (relative, posix), or "prompts"."""
    import yaml

    try:
        data = yaml.safe_load((root / "ract.yaml").read_text(encoding="utf-8")) or {}
        value = data.get("prompts_dir") if isinstance(data, dict) else None
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        value = None  # a missing or broken ract.yaml is reported where it is loaded
    text = str(value or "prompts").replace("\\", "/").strip("/")
    return text or "prompts"


def _in_venv(root: Path, rel: str) -> bool:
    """True when a folder above *rel* holds ``pyvenv.cfg`` (a virtual environment)."""
    parts = rel.split("/")[:-1]
    for i in range(1, len(parts) + 1):
        if (root.joinpath(*parts[:i]) / "pyvenv.cfg").is_file():
            return True
    return False


def path_tier(root: Path, rel: str) -> CapabilityTier:
    """The tier of writing *rel* (D3). Raises ToolRefused for a protected path."""
    posix = rel.replace("\\", "/").strip("/")
    parts = [p.casefold() for p in posix.split("/") if p]
    if not parts:
        raise ToolRefused("the project root itself cannot be written", "name a file")
    if any(p in (".git", ".ract") for p in parts) or any(
        p in AGENT_CONFIG_DIRS for p in parts
    ):
        raise ToolRefused(
            f"{posix} is under a protected directory (.git, .ract or an agent "
            "configuration directory) and no tool writes there",
            "write a project file instead",
        )
    folded = "/".join(parts)
    prompts = _prompts_dir(root).casefold()
    if parts[-1] in GUIDANCE_FILES or folded == "ract.yaml":
        return CapabilityTier.TIER_2_ENV
    if folded == prompts or folded.startswith(prompts + "/"):
        return CapabilityTier.TIER_2_ENV
    for pattern in EXECUTABLE_CONFIG_GLOBS:
        if fnmatch.fnmatchcase(folded, pattern) or (
            pattern.endswith("/*") and folded.startswith(pattern[:-1])
        ):
            return CapabilityTier.TIER_2_ENV
    if _in_venv(root, posix):
        return CapabilityTier.TIER_2_ENV
    return CapabilityTier.TIER_1_WRITE


_ORDER = {
    CapabilityTier.TIER_0_READ: 0,
    CapabilityTier.TIER_1_WRITE: 1,
    CapabilityTier.TIER_2_ENV: 2,
    CapabilityTier.TIER_3_EXTERNAL: 3,
}


def highest(*tiers: CapabilityTier) -> CapabilityTier:
    return max(tiers, key=lambda t: _ORDER[t])


def targets(name: str, args: BaseModel) -> list[str]:
    """The paths a call writes, removes or creates."""
    if isinstance(args, MoveFileArgs):
        return [args.path, args.destination]
    if isinstance(args, ApplyPatchArgs):
        return [f.path for f in _parse_patch(args.patch)]
    path = getattr(args, "path", None)
    return [path] if path and name != "repo_map" else []


def call_tier(spec: ToolSpec, args: BaseModel, root: Path) -> CapabilityTier:
    """The tier of this call: the declared tier raised by the paths it touches (D1, D3)."""
    tier = spec.tier
    if spec.mutates:
        for rel in targets(spec.name, args):
            tier = highest(tier, path_tier(root, rel))
    return tier


# ------------------------------------------------------------------ helpers


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _target(root: Path, raw: str) -> tuple[Path, str]:
    """The file *raw* names for a write, and its relative form; ToolRefused when refused."""
    try:
        full = require_workspace_path(root, raw, purpose="write")
    except WorkspacePathRefused as exc:
        raise ToolRefused(str(exc), "use a path inside the project") from exc
    rel = Path(os.path.relpath(full, os.path.realpath(root))).as_posix()
    path_tier(root, rel)  # raises for a protected path
    return full, rel


def _text_of(data: bytes, rel: str) -> str:
    """The file as text without its BOM; ToolRefused when it is not clean UTF-8."""
    try:
        return data.removeprefix(_BOM).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolRefused(
            f"{rel} is not clean UTF-8 (byte {exc.start}); it can be read and not edited",
            "edit a text file, or change this one yourself",
        ) from exc


def _existing(full: Path, rel: str, expected: str | None) -> bytes:
    """The bytes of an existing file whose digest is *expected*."""
    if not full.is_file():
        raise ToolRefused(f"{rel} does not exist", "list_dir shows what is there")
    data = full.read_bytes()
    if expected is None:
        raise ToolRefused(
            f"{rel} exists; changing it needs expected_digest",
            "read_file gives the file's digest; pass it as expected_digest",
        )
    now = _digest(data)
    if now != expected:
        raise ToolRefused(
            f"{rel} changed since it was read (digest {now[:12]}, expected {expected[:12]})",
            "re-read the file; it changed since your last read",
        )
    return data


def _styled(new_text: str, old: bytes | None) -> bytes:
    """*new_text* in the old file's style: its BOM and its line endings."""
    text = new_text.replace("\r\n", "\n")
    if old is not None and old.count(b"\r\n") * 2 > old.count(b"\n"):
        text = text.replace("\n", "\r\n")
    data = text.encode("utf-8")
    if old is not None and old.startswith(_BOM):
        data = _BOM + data
    return data


def _replace(full: Path, data: bytes) -> None:
    """Write *data* to *full* through a temporary file in the same folder."""
    full.parent.mkdir(parents=True, exist_ok=True)
    temp = full.with_name(f".{full.name}.ract-tmp")
    try:
        temp.write_bytes(data)
        os.replace(temp, full)
    finally:
        if temp.exists():
            temp.unlink()


def _result(
    action: str, rel: str, before: bytes | None, after: bytes | None
) -> ToolResult:
    """The result of a write that happened; the path is offered to the verifier (B-192)."""
    turn_context.note_changed(rel, after)
    facts = {
        "path": rel,
        "digest_before": _digest(before) if before is not None else None,
        "digest_after": _digest(after) if after is not None else None,
    }
    return ToolResult(text=f"{action} {rel}", facts=facts)


# ------------------------------------------------------------------ the tools


def write_file(root: Path, args: WriteFileArgs) -> ToolResult:
    if not args.content.strip():
        raise ToolRefused("an empty body is refused", "write the file's full content")
    full, rel = _target(root, args.path)
    if full.exists():
        if args.create:
            raise ToolRefused(
                f"{rel} exists; create refuses it", "pass expected_digest to replace it"
            )
        old = _existing(full, rel, args.expected_digest)
        _text_of(old, rel)
        data = _styled(args.content, old)
        _replace(full, data)
        return _result("wrote", rel, old, data)
    if not args.create:
        raise ToolRefused(
            f"{rel} does not exist", "pass create=true to make a new file"
        )
    data = _styled(args.content, None)
    _replace(full, data)
    return _result("created", rel, None, data)


def edit_file(root: Path, args: EditFileArgs) -> ToolResult:
    full, rel = _target(root, args.path)
    old = _existing(full, rel, args.expected_digest)
    text = _text_of(old, rel).replace("\r\n", "\n")
    needle = args.old.replace("\r\n", "\n")
    count = text.count(needle)
    if count == 0:
        raise ToolRefused(
            f"the text to replace is not in {rel}",
            "re-read the file and copy the text exactly",
        )
    if count > 1 and not args.replace_all:
        raise ToolRefused(
            f"the text to replace occurs {count} times in {rel}",
            "add surrounding lines so it occurs once, or set replace_all",
        )
    new_text = text.replace(needle, args.new.replace("\r\n", "\n"))
    if not new_text.strip():
        raise ToolRefused(
            f"the edit would leave {rel} empty", "use delete_file to remove a file"
        )
    data = _styled(new_text, old)
    _replace(full, data)
    return _result("edited", rel, old, data)


def delete_file(root: Path, args: DeleteFileArgs) -> ToolResult:
    full, rel = _target(root, args.path)
    old = _existing(full, rel, args.expected_digest)
    full.unlink()
    return _result("deleted", rel, old, None)


def move_file(root: Path, args: MoveFileArgs) -> ToolResult:
    full, rel = _target(root, args.path)
    dest, dest_rel = _target(root, args.destination)
    if dest.exists():
        raise ToolRefused(
            f"{dest_rel} exists; move_file refuses it", "choose a new destination"
        )
    old = _existing(full, rel, args.expected_digest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(full, dest)
    result = _result("moved", rel, old, old)
    turn_context.note_changed(rel, None)
    turn_context.note_changed(dest_rel, old)
    return ToolResult(
        text=f"moved {rel} to {dest_rel}",
        facts={**result.facts, "destination": dest_rel},
    )


# ------------------------------------------------------------------ apply_patch


class _FilePatch:
    def __init__(self, old_path: str | None, new_path: str | None) -> None:
        self.old_path = old_path
        self.new_path = new_path
        self.hunks: list[tuple[int, list[str]]] = []

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _header_path(line: str) -> str | None:
    value = line[4:].split("\t")[0].strip()
    if value == "/dev/null":
        return None
    if value.startswith(("a/", "b/")):
        value = value[2:]
    return value


def _parse_patch(patch: str) -> list[_FilePatch]:
    """The files of a unified diff, with their hunks; ToolRefused when it is not one."""
    lines = patch.replace("\r\n", "\n").split("\n")
    files: list[_FilePatch] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if (
            line.startswith("--- ")
            and i + 1 < len(lines)
            and lines[i + 1].startswith("+++ ")
        ):
            current = _FilePatch(_header_path(line), _header_path(lines[i + 1]))
            files.append(current)
            i += 2
            while i < len(lines) and lines[i].startswith("@@"):
                match = _HUNK.match(lines[i])
                if match is None:
                    raise ToolRefused(
                        f"bad hunk header: {lines[i][:80]}", "send a unified diff"
                    )
                old_count = int(match.group(2) or "1")
                new_count = int(match.group(4) or "1")
                body: list[str] = []
                i += 1
                seen_old = seen_new = 0
                while i < len(lines) and (seen_old < old_count or seen_new < new_count):
                    piece = lines[i]
                    if piece.startswith("\\"):
                        i += 1
                        continue
                    mark = piece[:1] or " "
                    if mark not in " +-":
                        break
                    if mark in " -":
                        seen_old += 1
                    if mark in " +":
                        seen_new += 1
                    body.append(mark + piece[1:])
                    i += 1
                if seen_old != old_count or seen_new != new_count:
                    raise ToolRefused(
                        f"a hunk in {current.path} does not match its line counts",
                        "send the diff as git diff writes it",
                    )
                current.hunks.append((int(match.group(1)), body))
            continue
        i += 1
    if not files:
        raise ToolRefused(
            "the patch names no file", "send a unified diff with --- and +++ headers"
        )
    return files


def _patched(text: str, file: _FilePatch, rel: str) -> str:
    """*text* with every hunk of *file* applied; ToolRefused when a hunk does not fit."""
    lines = text.split("\n") if text else []
    trailing = text.endswith("\n")
    if trailing:
        lines = lines[:-1]
    out: list[str] = []
    pos = 0
    for start, body in file.hunks:
        at = max(start - 1, 0) if start else 0
        old_part = [b[1:] for b in body if b[0] in " -"]
        if lines[at : at + len(old_part)] != old_part:
            raise ToolRefused(
                f"a hunk of {rel} does not match the file at line {start}",
                "re-read the file",
            )
        if at < pos:
            raise ToolRefused(
                f"the hunks of {rel} overlap", "send the diff as git diff writes it"
            )
        out += lines[pos:at]
        out += [b[1:] for b in body if b[0] in " +"]
        pos = at + len(old_part)
    out += lines[pos:]
    return "\n".join(out) + ("\n" if trailing or not text else "")


def apply_patch(root: Path, args: ApplyPatchArgs) -> ToolResult:
    """All or nothing: every file is computed first, then written."""
    files = _parse_patch(args.patch)
    planned: list[tuple[Path, str, bytes | None, bytes | None]] = []
    for file in files:
        full, rel = _target(root, file.path)
        if file.old_path is None:  # a new file
            if full.exists():
                raise ToolRefused(
                    f"{rel} exists; the patch creates it", "re-read the project"
                )
            created = _patched("", file, rel)
            planned.append((full, rel, None, _styled(created, None)))
            continue
        if not full.is_file():
            raise ToolRefused(f"{rel} does not exist", "list_dir shows what is there")
        current = full.read_bytes()
        text = _text_of(current, rel).replace("\r\n", "\n")
        if file.new_path is None:  # a deleted file
            if _patched(text, file, rel).strip():
                raise ToolRefused(
                    f"the patch deletes {rel} but does not remove all its lines",
                    "re-read the file",
                )
            planned.append((full, rel, current, None))
            continue
        planned.append(
            (full, rel, current, _styled(_patched(text, file, rel), current))
        )
    done: list[tuple[Path, bytes | None]] = []
    try:
        for full, _rel, old, new in planned:
            if new is None:
                full.unlink()
            else:
                _replace(full, new)
            done.append((full, old))
    except OSError as exc:
        for full, old in reversed(done):  # put back what was written
            if old is None:
                full.unlink(missing_ok=True)
            else:
                _replace(full, old)
        raise ToolRefused(
            f"the patch could not be written ({exc}); nothing changed", "try again"
        ) from exc
    changed: list[dict[str, Any]] = [
        {
            "path": rel,
            "digest_before": _digest(old) if old is not None else None,
            "digest_after": _digest(new) if new is not None else None,
        }
        for _full, rel, old, new in planned
    ]
    for _full, rel, _old, new in planned:
        turn_context.note_changed(rel, new)
    return ToolResult(
        text="patched " + ", ".join(c["path"] for c in changed),
        facts={"files": changed},
    )


# ------------------------------------------------------------------ repo_map


def repo_map(root: Path, args: RepoMapArgs) -> ToolResult:
    """Every project file, and the top-level classes and functions of each Python file."""
    from ract.tools.read import _resolve, _walk

    start, rel = _resolve(root, args.path)
    base = Path(os.path.realpath(root))
    files = _walk(base, start if start.is_dir() else start.parent, args.include_ignored)
    lines: list[str] = []
    for name in files[:MAP_MAX_FILES]:
        entry = name
        if name.endswith(".py"):
            try:
                tree = ast.parse((base / name).read_text(encoding="utf-8"))
                names = [
                    node.name
                    for node in tree.body
                    if isinstance(
                        node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
                    )
                ]
                if names:
                    entry += ": " + ", ".join(names[:40])
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
                entry += ": (not parsed)"
        lines.append(entry)
    more = len(files) - MAP_MAX_FILES
    if more > 0:
        lines.append(f"... and {more} more files")
    return ToolResult(
        text="\n".join(lines) or "no files",
        facts={"files": min(len(files), MAP_MAX_FILES), "root": rel},
        truncated=more > 0,
    )


WRITE_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "write_file",
        CapabilityTier.TIER_1_WRITE,
        WriteFileArgs,
        True,
        WRITE_CAP_BYTES,
        write_file,
    ),
    ToolSpec(
        "edit_file",
        CapabilityTier.TIER_1_WRITE,
        EditFileArgs,
        True,
        WRITE_CAP_BYTES,
        edit_file,
    ),
    ToolSpec(
        "delete_file",
        CapabilityTier.TIER_1_WRITE,
        DeleteFileArgs,
        True,
        WRITE_CAP_BYTES,
        delete_file,
    ),
    ToolSpec(
        "move_file",
        CapabilityTier.TIER_1_WRITE,
        MoveFileArgs,
        True,
        WRITE_CAP_BYTES,
        move_file,
    ),
    ToolSpec(
        "apply_patch",
        CapabilityTier.TIER_1_WRITE,
        ApplyPatchArgs,
        True,
        WRITE_CAP_BYTES,
        apply_patch,
    ),
    ToolSpec(
        "repo_map",
        CapabilityTier.TIER_0_READ,
        RepoMapArgs,
        False,
        MAP_CAP_BYTES,
        repo_map,
    ),
)
