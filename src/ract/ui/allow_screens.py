"""The allowlist and approval-prompt screens of slice (d) (B-113, ADR-0048 D4 and D6).

Pure: plain data in, text out. No rule is matched here, no approval is recorded, no file is read.
The BUILDER's matcher decides; these screens say the decision in words. Every argv, path and
rule text that comes from a repository or a model is escaped (``\\x1b``, ``\\u202e``) before it is
shown. Text folds by terminal columns (``ract.cell_wrap``), so 80, 60 and 40 columns are one code
path. Rich output bolds the question lines; plain output and NO_COLOR output have no markup.

The three screens:

- ``allowed_by_rule_lines``: a command that matches an allow rule in ``allowlist`` mode runs
  without asking. The line names the rule and its argv prefix, so the operator sees why it ran.
- ``session_approvals_lines``: the approvals made this session (``/permissions`` lists them).
  Each names its argv prefix and its scope, and says that a session approval never carries over
  to ``/resume``.
- ``entry_point_question_lines``: a changed repository-defined entry point (a test, conftest or runner
  configuration file) always asks, even under a matching allow rule (G-214). The question names the
  file and why it asks now: written by the model this session, or changed since the grant was signed.
"""

from __future__ import annotations

from dataclasses import dataclass

from ract.cell_wrap import wrap_cells, wrap_exact
from ract.session_events import screen_text

ENTRY_CHOICES = "[y]es, once  [n]o"
CARRY_STATEMENT = "session approvals do not carry over to /resume"


def escape_controls(text: str) -> str:
    """Every control, format and direction character escaped (B-204: one shared escape)."""
    return screen_text(text)


def _fold_exact(text: str, width: int, indent: str = "    ") -> list[str]:
    """A command or a path: every character kept, broken only at the width (B-184)."""
    return wrap_exact(escape_controls(text), width, subsequent_indent=indent) or [""]


def _fold(text: str, width: int, indent: str = "    ") -> list[str]:
    return wrap_cells(escape_controls(text), width, subsequent_indent=indent) or [""]


def _bold(text: str, rich: bool) -> str:
    return f"[bold]{text}[/bold]" if rich else text


def _argv_text(argv: tuple[str, ...]) -> str:
    return " ".join(escape_controls(arg) for arg in argv)


@dataclass(frozen=True)
class AllowRule:
    """A rule the policy allows. ``prefix`` is the argv prefix it matches."""

    rule_id: str
    prefix: tuple[str, ...]


def allowed_by_rule_lines(
    argv: tuple[str, ...], rule: AllowRule, width: int, *, rich: bool = False
) -> list[str]:
    """The line shown when a command runs without asking because an allow rule matches it."""
    out = _fold(
        _bold("ran without asking: an allow rule matches", rich), width, indent="  "
    )
    out += _fold(f"argv: {_argv_text(argv)}", width)
    out += _fold(
        f"rule {escape_controls(rule.rule_id)}: prefix {_argv_text(rule.prefix)}", width
    )
    out += _fold(
        "allowlist mode: tier 2 and the always-ask list still ask", width, indent="  "
    )
    return out


@dataclass(frozen=True)
class SessionApproval:
    """An approval made this session: the argv prefix the operator picked, and its scope."""

    prefix: tuple[str, ...]
    scope: str = "this session"


def session_approvals_lines(approvals: list[SessionApproval], width: int) -> list[str]:
    """The approvals of this session, one line each, then the statement about /resume."""
    if not approvals:
        return _fold("no approvals this session", width, indent="  ")
    out: list[str] = []
    for approval in approvals:
        out += _fold(
            f"{_argv_text(approval.prefix)}: {escape_controls(approval.scope)}", width
        )
    out += _fold(CARRY_STATEMENT, width, indent="  ")
    return out


@dataclass(frozen=True)
class EntryPointChange:
    """A repository-defined entry point and why it asks now."""

    path: str
    reason: str  # "written by the model this session" or "changed since the grant was signed"


def entry_point_question_lines(
    change: EntryPointChange, width: int, *, rich: bool = False
) -> list[str]:
    """The question put back when a changed entry point would run: it asks even under a match."""
    out = _fold(
        _bold("this file runs your tests and it changed", rich), width, indent="  "
    )
    out += _fold_exact(f"file: {change.path}", width)
    out += _fold(f"why it asks now: {escape_controls(change.reason)}", width)
    out += _fold("an allow rule does not answer for it", width, indent="  ")
    out += _fold(_bold(ENTRY_CHOICES, rich), width, indent="  ")
    return out
