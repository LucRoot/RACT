"""Large outputs are offloaded; the model reads slices (ADR-0049 D9, B-174).

An output over OFFLOAD_THRESHOLD bytes is stored whole under the run's folder, one file per
(session, turn, name). The model gets a labelled stub: the data label, the size, the first and last
lines, and a handle. The summary is made by this module, never by a model. A slice is read with
read_slice, which is bounded, refuses binary files, refuses any handle that is not this session's,
and passes the outbound secret scan before the text can enter a request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ract import egress_scan
from ract.tools import UNTRUSTED_LABEL

OFFLOAD_THRESHOLD = 8 * 1024
SUMMARY_CAP = 4 * 1024
SLICE_MAX_LINES = 200
SLICE_MAX_BYTES = 16 * 1024
HEAD_LINES = 20
TAIL_LINES = 40
BINARY_PROBE_BYTES = 8 * 1024

_PART = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}"
HANDLE_PATTERN = re.compile(rf"^artifact:({_PART})/(\d{{1,6}})/({_PART})$")


class OffloadError(ValueError):
    """A stored output or a handle was refused. The message names the reason."""


@dataclass(frozen=True)
class Placed:
    text: str
    handle: str | None
    offloaded: bool


@dataclass(frozen=True)
class Slice:
    text: str
    lines_returned: int
    note: str


class OffloadStore:
    """The offloaded outputs of one session, under one folder."""

    def __init__(self, folder: Path, *, session_id: str) -> None:
        if not re.fullmatch(_PART, session_id):
            raise OffloadError(f"session id {session_id!r} is not a plain name")
        self.folder = folder
        self.session_id = session_id

    def place(self, text: str, *, turn: int, name: str) -> Placed:
        """Return the text itself when it is small, or a labelled stub when it is offloaded."""
        data = text.encode("utf-8")
        if len(data) <= OFFLOAD_THRESHOLD:
            return Placed(text=text, handle=None, offloaded=False)
        if not re.fullmatch(_PART, name):
            raise OffloadError(f"output name {name!r} is not a plain name")
        handle = f"artifact:{self.session_id}/{turn}/{name}"
        path = self._path(handle)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        lines = text.splitlines()
        head = "\n".join(lines[:HEAD_LINES])
        tail = "\n".join(lines[-TAIL_LINES:]) if len(lines) > HEAD_LINES else ""
        summary = (
            f"[offloaded: {len(lines)} lines, {len(data)} bytes]\n"
            f"first {min(HEAD_LINES, len(lines))} lines:\n{head}\n"
            f"last {min(TAIL_LINES, len(lines))} lines:\n{tail}\n"
            f"read more with read_slice on {handle}"
        )
        summary = _cap_text(summary, SUMMARY_CAP)
        return Placed(text=f"{UNTRUSTED_LABEL}\n{summary}", handle=handle, offloaded=True)

    def read_slice(self, handle: str, *, start_line: int, count: int) -> Slice:
        """Return at most SLICE_MAX_LINES lines and SLICE_MAX_BYTES bytes, from start_line."""
        match = HANDLE_PATTERN.match(handle)
        if match is None:
            raise OffloadError(f"handle {handle!r} is not an artifact pointer")
        if match.group(1) != self.session_id:
            raise OffloadError("handle belongs to another session")
        if start_line < 1 or count < 1:
            raise OffloadError("start_line and count must be 1 or more")
        path = self._path(handle)
        if not path.is_file():
            raise OffloadError(f"no stored output for {handle}")
        raw = path.read_bytes()
        if b"\x00" in raw[:BINARY_PROBE_BYTES]:
            raise OffloadError("stored output is binary and cannot be read as lines")
        lines = raw.decode("utf-8", errors="replace").splitlines()
        if start_line > len(lines):
            return Slice(
                text=f"{UNTRUSTED_LABEL}\n",
                lines_returned=0,
                note=f"start_line {start_line} is past the end ({len(lines)} lines)",
            )
        picked: list[str] = []
        size = 0
        for line in lines[start_line - 1 : start_line - 1 + min(count, SLICE_MAX_LINES)]:
            encoded = len((line + "\n").encode("utf-8"))
            if size + encoded > SLICE_MAX_BYTES:
                break
            picked.append(line)
            size += encoded
        body, counts = egress_scan.scan_text("\n".join(picked) + ("\n" if picked else ""))
        note = egress_scan.describe(counts) if counts else ""
        return Slice(text=f"{UNTRUSTED_LABEL}\n{body}", lines_returned=len(picked), note=note)

    def _path(self, handle: str) -> Path:
        match = HANDLE_PATTERN.match(handle)
        if match is None:
            raise OffloadError(f"handle {handle!r} is not an artifact pointer")
        path = self.folder / match.group(1) / match.group(2) / f"{match.group(3)}.txt"
        if not path.resolve().is_relative_to(self.folder.resolve()):
            raise OffloadError("handle leaves the run folder")
        return path


def _cap_text(text: str, cap_bytes: int) -> str:
    data = text.encode("utf-8")
    if len(data) <= cap_bytes:
        return text
    return data[:cap_bytes].decode("utf-8", errors="ignore") + "\n[cut: summary capped]"
