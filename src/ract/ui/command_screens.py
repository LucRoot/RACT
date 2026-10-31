"""The command screens of slice (c): the tier-3 approval prompt, the structured test-result
view and the verdict line with the trace-chain statement (B-112, ADR-0048 D6 and D10,
decision package condition 4).

Pure: plain data in, text out. No command runs, no key is read, no event is emitted. The
BUILDER wires these into the approval path and the verdict (slice (c)). Control characters
in argv, paths and names are shown escaped (``\\x1b``), never printed raw. Text is folded
by terminal columns (``ract.cell_wrap``), so 80, 60 and 40 columns are one code path. Rich
output bolds the question and the verdict; plain output has none.

Fields not in ADR-0048 D6 and D10 are listed in the READY note as questions: the exact form
of the environment-names line (D10 names the names only), how the limits are shown (D5 lists
them), and the step trust states (D6 says "the step's trust state" without the values).
"""

from __future__ import annotations

from dataclasses import dataclass

from ract.cell_wrap import wrap_cells, wrap_exact
from ract.session_events import safe_text, screen_text

CHOICES = "[o]nce  [s]ession  [a]lways  [d]eny"
TRACE_STATEMENT = (
    "command records are in the trace; they are not part of the signed Rootknot"
)


def escape_controls(text: str) -> str:
    """Every control, format and direction character escaped (B-204: one shared escape)."""
    return screen_text(text)


def _fold_exact(text: str, width: int, indent: str = "    ") -> list[str]:
    """A command or a path: every character kept, broken only at the width (B-184)."""
    return wrap_exact(escape_controls(text), width, subsequent_indent=indent) or [""]


def _fold(text: str, width: int, indent: str = "    ") -> list[str]:
    return wrap_cells(text, width, subsequent_indent=indent) or [""]


def _bold(text: str, rich: bool) -> str:
    return f"[bold]{text}[/bold]" if rich else text


@dataclass(frozen=True)
class CommandRequest:
    """What the operator is asked to allow. ``reason`` is the model's stated reason."""

    argv: tuple[str, ...]
    executable: str
    cwd: str
    network: bool
    sandbox_enforced: bool
    env_names: tuple[str, ...] = ()
    limits: str = ""
    trust: str = ""
    reason: str = ""


def approval_prompt_lines(
    request: CommandRequest, width: int, *, rich: bool = False, choices: str = CHOICES
) -> list[str]:
    """The tier-3 prompt: full argv escaped, executable, cwd, network, sandbox, and the choices."""
    argv = " ".join(escape_controls(arg) for arg in request.argv)
    sandbox = (
        "enforced on this machine"
        if request.sandbox_enforced
        else "best effort: not enforced on this machine"
    )
    out = _fold(_bold("run this command? (tier 3)", rich), width, indent="  ")
    out += _fold_exact(f"argv: {argv}", width)
    out += _fold_exact(f"executable: {request.executable}", width)
    out += _fold_exact(f"cwd: {request.cwd}", width)
    out += _fold(f"network: {'on' if request.network else 'off'}", width)
    out += _fold(f"sandbox: {sandbox}", width)
    if request.env_names:
        names = ", ".join(escape_controls(name) for name in request.env_names)
        out += _fold(f"environment names passed: {names}", width)
    if request.limits:
        out += _fold(f"limits: {escape_controls(request.limits)}", width)
    if request.trust:
        out += _fold(f"step trust: {safe_text(request.trust)}", width)
    if request.reason:
        out += _fold(
            f"the model says (model text, not checked): {safe_text(request.reason)}",
            width,
        )
    out += _fold(_bold(choices, rich), width, indent="  ")
    return out


@dataclass(frozen=True)
class FailingTest:
    name: str
    message: str = ""


@dataclass(frozen=True)
class RunSummary:
    passed: (
        int | None
    )  # None when the runner's summary is not parsed (only pytest's is)
    failed: int | None
    skipped: int | None
    duration_s: float
    exit_code: int
    failing: tuple[FailingTest, ...] = ()


def result_lines(summary: RunSummary, width: int, *, rich: bool = False) -> list[str]:
    """The structured result of a test run: counts and time on one line, each failure after it."""
    if summary.passed is None or summary.failed is None or summary.skipped is None:
        # A runner whose summary RACT does not parse (only pytest's is parsed): say so, do not guess.
        head = f"tests: counts not parsed ({summary.duration_s:.1f} s, exit {summary.exit_code})"
    else:
        head = (
            f"tests: {summary.passed} passed, {summary.failed} failed, "
            f"{summary.skipped} skipped ({summary.duration_s:.1f} s, exit {summary.exit_code})"
        )
    out = _fold(_bold(head, rich), width, indent="  ")
    for failing in summary.failing:
        out += _fold(f"failed: {escape_controls(failing.name)}", width, indent="    ")
        if failing.message:
            out += _fold(safe_text(failing.message), width, indent="      ")
    return out


def verdict_lines(
    verdict: str, command_records: int, width: int, *, rich: bool = False
) -> list[str]:
    """The verdict line, then the sentence that says where the command records bind."""
    noun = "record" if command_records == 1 else "records"
    out = _fold(_bold(f"verdict: {safe_text(verdict)}", rich), width, indent="  ")
    # ADR-0048 D10: said wherever the verdict speaks of a run; a turn that ran
    # no command has no records to place.
    if command_records:
        out += _fold(
            f"{command_records} command {noun}: {TRACE_STATEMENT}", width, indent="  "
        )
    return out
