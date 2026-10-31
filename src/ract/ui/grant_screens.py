"""The guided grant flow and the /permissions view as text (B-111, ADR-0048 D13 and D3).

Pure: plain data in, text out. No key is created, no passphrase is read, no policy is written or
signed here: the BUILDER's guided flow does those and passes the results in. Each step of
``ract policy init --guided`` is one screen. Every name, argv and path that comes from a repository
or a model is escaped before it is shown (control and bidirectional characters as ``\\xNN`` or
``\\uNNNN``). Text folds by terminal columns (``ract.cell_wrap``), so 80, 60 and 40 columns are one
code path. Rich output bolds the question lines; plain and NO_COLOR output have no markup.

The field explanations are one line each, as D13 asks: argv prefix, network, time limit, working
directory, environment names, and home. A line says what the rule declares; when the sandbox does
not enforce, the network line says so (G1, G-216 wording).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ract.cell_wrap import wrap_cells

PASSPHRASE_PROMPT = "passphrase for the operator key (typed here; never read from an environment variable)"
SIGN_CHOICES = "[y]es, sign once  [n]o, sign nothing"


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


def _bold(text: str, rich: bool) -> str:
    return f"[bold]{text}[/bold]" if rich else text


def _argv(argv: tuple[str, ...]) -> str:
    return " ".join(escape_controls(arg) for arg in argv)


@dataclass(frozen=True)
class DetectedRunner:
    name: str
    argv: tuple[str, ...]
    evidence: str  # the file that showed it, e.g. "pyproject.toml has [tool.pytest]"
    # B-142: "linter", "type checker", "formatter" or "build" for the verifiers.
    kind: str = "test runner"


@dataclass(frozen=True)
class ProposedRule:
    rule_id: str
    argv: tuple[str, ...]
    network: bool = False
    timeout_minutes: int = 15
    cwd: str = "."
    env_names: tuple[str, ...] = ()
    home: str = "isolated"
    sandbox_enforced: bool = False


def detected_runner_lines(runner: DetectedRunner | None, width: int) -> list[str]:
    if runner is None:
        return _fold(
            "no test runner found in this project; nothing to grant yet",
            width,
            indent="  ",
        )
    out = _fold(
        _bold(f"found the {runner.kind}: {runner.name}", False), width, indent="  "
    )
    out += _fold(f"the rule would allow: {_argv(runner.argv)}", width)
    out += _fold(f"seen in: {escape_controls(runner.evidence)}", width)
    return out


def field_explanation_lines(rule: ProposedRule, width: int) -> list[str]:
    """One line per field, the wording D13 asks for. The network line says what is enforced."""
    if rule.network:
        network = "network: on: the command may reach the network"
    elif rule.sandbox_enforced:
        network = "network: off: the command runs without the network"
    else:
        network = "network: off: declared off; this machine does not enforce it"
    lines = [
        f"argv: {_argv(rule.argv)}: the only command this rule allows, matched from its first word",
        network,
        f"time limit: {rule.timeout_minutes} minutes, then the command is stopped",
        f"working folder: {escape_controls(rule.cwd)}: the command starts here",
    ]
    if rule.env_names:
        names = ", ".join(escape_controls(name) for name in rule.env_names)
        lines.append(f"environment passed: {names}")
    else:
        lines.append("environment passed: none beyond the defaults")
    lines.append(
        "home: isolated: the command gets a temporary home folder"
        if rule.home == "isolated"
        else f"home: {escape_controls(rule.home)}: the command sees this home folder"
    )
    if not rule.sandbox_enforced:
        lines.append("it runs with your user's rights on this machine")
    out: list[str] = []
    for line in lines:
        out += _fold(line, width)
    return out


def proposed_rule_lines(
    rule: ProposedRule, width: int, *, rich: bool = False
) -> list[str]:
    out = _fold(
        _bold(f"proposed rule {escape_controls(rule.rule_id)}", rich),
        width,
        indent="  ",
    )
    out += field_explanation_lines(rule, width)
    return out


def policy_diff_lines(diff: list[str], width: int) -> list[str]:
    """The policy file as a diff: lines that start with ``+``, ``-`` or a space, escaped and folded."""
    if not diff:
        return ["the policy file would not change"]
    out: list[str] = []
    for line in diff:
        out += _fold(line, width, indent="  ")
    return out


def passphrase_prompt_lines(width: int, *, has_terminal: bool) -> list[str]:
    """The passphrase step. Without a terminal nothing can be signed, and the screen says so."""
    if not has_terminal:
        return _fold(
            "no terminal to type a passphrase at: nothing was signed. Run the command again at a terminal.",
            width,
            indent="  ",
        )
    return _fold(PASSPHRASE_PROMPT, width, indent="  ")


def signed_result_lines(
    rule_id: str, expires: str, status: str, width: int
) -> list[str]:
    """The result after the signature: the rule, its expiry, and the status line it now shows."""
    out = _fold(
        f"signed: rule {escape_controls(rule_id)} expires {escape_controls(expires)}",
        width,
        indent="  ",
    )
    out += _fold(f"status line now: {escape_controls(status)}", width)
    out += _fold(
        "run it with: ract run (the rule is used only for the command it names)",
        width,
    )
    return out


def sign_question_lines(width: int, *, rich: bool = False) -> list[str]:
    return _fold(_bold(f"sign this rule? {SIGN_CHOICES}", rich), width, indent="  ")


@dataclass(frozen=True)
class PermissionsView:
    """What /permissions shows: the rules, the deny rules, the largest mode, the expiry, the sandbox."""

    rules: tuple[ProposedRule, ...] = ()
    deny: tuple[str, ...] = ()
    max_mode: str = "ask"
    expires: str = ""
    sandbox_enforced: bool = False
    notes: list[str] = field(default_factory=list)


def permissions_lines(view: PermissionsView, width: int) -> list[str]:
    out: list[str] = []
    if not view.rules:
        out += _fold("no rule is granted in this project", width, indent="  ")
    for rule in view.rules:
        out += _fold(f"rule {escape_controls(rule.rule_id)}: {_argv(rule.argv)}", width)
    for pattern in view.deny:
        out += _fold(f"deny: {escape_controls(pattern)}", width)
    out += _fold(f"largest mode: {escape_controls(view.max_mode)}", width)
    if view.expires:
        out += _fold(f"expires: {escape_controls(view.expires)}", width)
    sandbox = (
        "sandbox: enforced on this machine"
        if view.sandbox_enforced
        else "sandbox: best effort, not enforced on this machine"
    )
    out += _fold(sandbox, width)
    for note in view.notes:
        out += _fold(f"note: {escape_controls(note)}", width)
    return out
