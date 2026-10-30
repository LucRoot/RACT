"""The workspace screens of slice (a): diff.proposed, the apply result, the checkpoint and
restore listings, the preparing line and the not-a-git-repository offer (B-110, ADR-0047 D6).

Pure: plain data in, text out. No event is emitted, no file is read, no worktree is made.
The BUILDER wires these screens into the step loop (slice (a)). Every path, name and
argv that comes from a repository or a model goes through ``safe_text`` before it is
shown. Text is folded by terminal columns (``ract.cell_wrap``), so 80, 60 and 40 columns
are one code path. Rich output adds bold markup on the hunk headers and the offer's
question; plain output has none.

Fields not defined in ADR-0047 D6 are listed in the READY note, not invented here:
the hunk id form (this module uses ``<path>#<n>``, counting from 1 per file), the
checkpoint's time format, and the wording of the restore preview.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ract.cell_wrap import wrap_cells
from ract.session_events import safe_text

PENDING_ROOT = ".ract/pending"


@dataclass(frozen=True)
class Hunk:
    """One hunk of a proposed change. ``lines`` are unified-diff lines (``+``, ``-``, `` ``)."""

    id: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class FileProposal:
    path: str
    hunks: tuple[Hunk, ...]


@dataclass(frozen=True)
class ApplyResult:
    """What an apply did. ``pending`` maps a skipped path to its saved patch file."""

    applied_hunks: int
    applied_files: int
    skipped: tuple[str, ...] = ()
    session: str = ""
    pending: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Checkpoint:
    number: int
    when: str
    turn: str
    files: int
    undone: bool = False


def _fold(text: str, width: int, indent: str = "    ") -> list[str]:
    return wrap_cells(safe_text(text), width, subsequent_indent=indent) or [""]


def _bold(text: str, rich: bool) -> str:
    return f"[bold]{text}[/bold]" if rich else text


def hunk_id(path: str, number: int) -> str:
    """The id a reviewer types for a hunk: ``<path>#<n>``, n counting from 1."""
    return f"{path}#{number}"


def diff_proposed_lines(
    files: list[FileProposal], width: int, *, rich: bool = False
) -> list[str]:
    """The proposed change: per file a header, per hunk its id, range and diff lines."""
    out: list[str] = []
    for proposal in files:
        added = sum(
            1 for h in proposal.hunks for line in h.lines if line.startswith("+")
        )
        removed = sum(
            1 for h in proposal.hunks for line in h.lines if line.startswith("-")
        )
        count = len(proposal.hunks)
        noun = "hunk" if count == 1 else "hunks"
        out += _fold(
            _bold(
                f"proposed {proposal.path}: {count} {noun}, +{added} -{removed}", rich
            ),
            width,
            indent="  ",
        )
        for hunk in proposal.hunks:
            head = (
                f"{hunk.id}: old {hunk.old_start},{hunk.old_count} "
                f"new {hunk.new_start},{hunk.new_count}"
            )
            out += _fold(_bold(head, rich), width, indent="  ")
            for line in hunk.lines:
                out += _fold(line, width, indent="  ")
    if not out:
        out.append("nothing proposed")
    return out


def apply_result_lines(result: ApplyResult, width: int) -> list[str]:
    """What the apply did: how many hunks went in, and each skipped file with its saved patch."""
    noun = "hunk" if result.applied_hunks == 1 else "hunks"
    files = "file" if result.applied_files == 1 else "files"
    out = _fold(
        f"applied {result.applied_hunks} {noun} in {result.applied_files} {files} "
        "(unstaged; review with git diff)",
        width,
        indent="  ",
    )
    for path in result.skipped:
        out += _fold(
            f"skipped {path}: it changed after RACT wrote it", width, indent="  "
        )
        patch = result.pending.get(path)
        if patch is None:
            patch = f"{PENDING_ROOT}/{result.session or '<session>'}/"
        out += _fold(f"patch saved under {patch}", width, indent="    ")
    return out


def checkpoint_lines(checkpoints: list[Checkpoint], width: int) -> list[str]:
    """``/checkpoint``: newest first, one line per checkpoint, the undone ones marked."""
    if not checkpoints:
        return ["no checkpoints in this session"]
    out: list[str] = []
    for cp in sorted(checkpoints, key=lambda c: c.number, reverse=True):
        mark = " (undone)" if cp.undone else ""
        files = "file" if cp.files == 1 else "files"
        out += _fold(
            f"{cp.number} {cp.when} {safe_text(cp.turn)}: {cp.files} {files}{mark}",
            width,
            indent="  ",
        )
    return out


def restore_preview_lines(
    number: int,
    restore: list[str],
    left_alone: list[str],
    width: int,
) -> list[str]:
    """``/restore <n>`` before it runs: the files it would put back, and the ones it leaves alone."""
    out = _fold(
        f"restore checkpoint {number}: {len(restore)} to put back", width, indent="  "
    )
    for path in restore:
        out += _fold(f"  back {path}", width, indent="    ")
    for path in left_alone:
        out += _fold(
            f"  left alone {path}: changed since checkpoint {number}",
            width,
            indent="    ",
        )
    return out


def preparing_line(seconds: float, width: int) -> str:
    """The line shown from the first mutating call until the worktree is ready."""
    text = f"preparing a workspace ({seconds:.0f} s)"
    return _fold(text, width, indent="  ")[0]


def not_git_offer_lines(
    command: str,
    left_out: list[str],
    width: int,
    *,
    rich: bool = False,
) -> list[str]:
    """The offer when the folder is not a git repository: the exact command, shown as tier 2."""
    out = _fold(
        "this folder is not a git repository. Edits need one: RACT would run",
        width,
        indent="  ",
    )
    out += _fold(f"  {command}", width, indent="    ")
    if left_out:
        names = ", ".join(sorted(left_out))
        out += _fold(
            f"sensitive files left out of the first commit: {names}", width, indent="  "
        )
    out += _fold(
        _bold("Run it? [y]es, approve  [n]o, stay read-only for this step", rich),
        width,
        indent="  ",
    )
    return out
