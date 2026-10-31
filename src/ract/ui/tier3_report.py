"""The report of `ract doctor --tier3` as text (B-147, the screen half).

Pure: a dataclass in, lines out. The BUILDER's doctor collects the facts (the grant, the key, the
window, the sandbox) and passes them here; this module says them in words, one line each, and ends
with the next command for each problem. Every name and path from the project or the grant is escaped.
The text fits 80, 60 and 40 columns. ``--json`` carries the same fields (the BUILDER's, not here).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ract.cell_wrap import wrap_cells


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
class GrantFacts:
    found: bool
    signed_by: str = ""
    expires: str = ""
    digest: str = ""  # the first characters only; never the whole digest


@dataclass(frozen=True)
class Tier3Facts:
    """What the doctor found. ``why_off`` is the reason tier 3 is off, empty when it is on."""

    grant: GrantFacts
    why_off: str
    key_present: bool
    key_location: str
    key_protection: str
    window: str  # "off", "10 minutes", "closed" or a sentence
    sandbox_backend: str
    sandbox_confines: str
    sandbox_does_not: str
    entry_point_record: str
    session_mode: str
    tools_available: tuple[str, ...] = ()
    tools_unavailable: tuple[str, ...] = ()
    next_steps: tuple[tuple[str, str], ...] = ()  # (problem, command)
    notes: list[str] = field(default_factory=list)


def tier3_report_lines(facts: Tier3Facts, width: int) -> list[str]:
    out = _fold("tier 3 (ract doctor --tier3)", width, indent="  ")
    out += _fold("grant:", width, indent="  ")
    if facts.grant.found:
        out += _fold(
            f"found, signed by {escape_controls(facts.grant.signed_by)}", width
        )
        out += _fold(f"expires {escape_controls(facts.grant.expires)}", width)
        out += _fold(f"digest starts {escape_controls(facts.grant.digest)}", width)
    else:
        out += _fold("none on file", width)
    out += _fold(
        f"why tier 3 is off: {escape_controls(facts.why_off)}"
        if facts.why_off
        else "tier 3 is on for this project",
        width,
        indent="  ",
    )
    out += _fold("operator key:", width, indent="  ")
    if facts.key_present:
        out += _fold(f"present, in {escape_controls(facts.key_location)}", width)
        out += _fold(f"protection: {escape_controls(facts.key_protection)}", width)
    else:
        out += _fold("not made yet (ract policy keygen makes it at a terminal)", width)
    out += _fold(f"unlock window: {escape_controls(facts.window)}", width, indent="  ")
    out += _fold("sandbox on this machine:", width, indent="  ")
    out += _fold(f"backend: {escape_controls(facts.sandbox_backend)}", width)
    out += _fold(f"confines: {escape_controls(facts.sandbox_confines)}", width)
    out += _fold(f"does not confine: {escape_controls(facts.sandbox_does_not)}", width)
    out += _fold(
        f"entry points: {escape_controls(facts.entry_point_record)}", width, indent="  "
    )
    out += _fold(
        f"session mode: {escape_controls(facts.session_mode)}", width, indent="  "
    )
    if facts.tools_available:
        out += _fold(
            f"tools the grant makes available: {', '.join(facts.tools_available)}",
            width,
            indent="  ",
        )
    if facts.tools_unavailable:
        out += _fold(
            f"tools it does not: {', '.join(facts.tools_unavailable)}",
            width,
            indent="  ",
        )
    for note in facts.notes:
        out += _fold(f"note: {escape_controls(note)}", width, indent="  ")
    if facts.next_steps:
        out += _fold("to fix:", width, indent="  ")
        for problem, command in facts.next_steps:
            out += _fold(
                f"{escape_controls(problem)}: run {escape_controls(command)}",
                width,
                indent="    ",
            )
    return out
