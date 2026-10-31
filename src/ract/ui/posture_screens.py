"""The sandbox screens of slice (e) (B-125, ADR-0048 D7): the doctor sandbox section, the
/permissions Sandbox line, and the approval-prompt sandbox line, for the three postures
enforced, best effort and none, at 80, 60 and 40 columns.

Pure: plain data in, text out. Nothing here probes the machine, runs a command or reads a file.
The honest wording is fixed here: a backend that does not enforce says "not enforced on this
machine"; "none" says that no sandbox applies at all. The BUILDER wires these with B-025.
Control characters in backend names and paths are shown escaped.
"""

from __future__ import annotations

from dataclasses import dataclass

from ract.cell_wrap import wrap_cells

ENFORCED = "enforced"
BEST_EFFORT = "best_effort"
NONE = "none"


def escape_controls(text: str) -> str:
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif code < 0x20 or 0x7F <= code <= 0x9F:
            out.append(f"\\x{code:02x}")
        elif (
            0x200E <= code <= 0x200F
            or 0x202A <= code <= 0x202E
            or 0x2066 <= code <= 0x2069
        ):
            out.append(f"\\u{code:04x}")
        else:
            out.append(ch)
    return "".join(out)


def _fold(text: str, width: int, indent: str = "    ") -> list[str]:
    return wrap_cells(escape_controls(text), width, subsequent_indent=indent) or [""]


@dataclass(frozen=True)
class SandboxPosture:
    """What the machine can do: the backend's name and its posture, and the limits applied."""

    backend: str
    posture: str  # ENFORCED, BEST_EFFORT or NONE
    limits: str = ""


def sandbox_line(posture: SandboxPosture) -> str:
    """The one line for /permissions and the approval prompt: the posture in honest words."""
    backend = escape_controls(posture.backend)
    if posture.posture == ENFORCED:
        return f"sandbox: enforced on this machine ({backend})"
    if posture.posture == BEST_EFFORT:
        return f"sandbox: best effort, not enforced on this machine ({backend})"
    return "sandbox: none; commands run with your user's rights"


def doctor_sandbox_lines(posture: SandboxPosture, width: int) -> list[str]:
    """The doctor's sandbox section: the line, the limits applied, and what a grant may say."""
    out = _fold("sandbox", width, indent="  ")
    out += _fold(sandbox_line(posture), width)
    if posture.limits:
        out += _fold(f"limits applied: {escape_controls(posture.limits)}", width)
    if posture.posture == BEST_EFFORT:
        out += _fold(
            "a grant must say sandbox: best_effort; this machine does not confine commands",
            width,
        )
    if posture.posture == NONE:
        out += _fold("commands cannot be granted tier 3 on this machine", width)
    return out


def permissions_sandbox_line(posture: SandboxPosture, width: int) -> list[str]:
    return _fold(sandbox_line(posture), width, indent="  ")


def approval_sandbox_line(posture: SandboxPosture, width: int) -> list[str]:
    """The approval prompt's sandbox line, with the wording a user needs before a yes."""
    if posture.posture == ENFORCED:
        text = (
            "sandbox: enforced here, so the command is confined to the project folder"
        )
    elif posture.posture == BEST_EFFORT:
        text = "sandbox: best effort; the command is NOT confined on this machine"
    else:
        text = "sandbox: none; the command runs with your user's rights"
    return _fold(text, width, indent="  ")
