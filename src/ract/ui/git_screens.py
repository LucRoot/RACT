"""The git tool prompts of slice (f) (B-126, ADR-0048 D8): the tier-2 commit prompt with its
secret-scan result, the branch and worktree prompts, and the tier-3 push prompt that names the
handshake.

Pure: plain data in, text out. Nothing here stages, commits, scans or pushes. The BUILDER wires
these with B-115. A commit message is the model's text and is labeled as such; every path,
branch name and message is escaped so a control character is visible, never printed raw.
"""

from __future__ import annotations

from dataclasses import dataclass

from ract.cell_wrap import wrap_cells

COMMIT_CHOICES = "[y]es, commit  [n]o, leave it staged"
BRANCH_CHOICES = "[y]es, do it  [n]o"
PUSH_CHOICES = "[n]o, do not push"


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
class SecretFinding:
    path: str
    kind: str  # the rule that matched, e.g. "api key shape"; never the secret itself


@dataclass(frozen=True)
class CommitRequest:
    message: str  # the model's text: labeled as such on the screen
    files: tuple[str, ...]
    findings: tuple[SecretFinding, ...] = ()


def commit_prompt_lines(request: CommitRequest, width: int) -> list[str]:
    """The commit prompt. A staged secret blocks the commit: the screen says so and offers no yes."""
    out = _fold("commit (tier 2)", width, indent="  ")
    out += _fold(f"files: {len(request.files)}", width)
    for path in request.files:
        out += _fold(f"  {escape_controls(path)}", width, indent="    ")
    out += _fold(
        f"message (the model wrote this text): {escape_controls(request.message)}",
        width,
    )
    if request.findings:
        out += _fold("secret scan: blocked; the commit is refused", width, indent="  ")
        for finding in request.findings:
            out += _fold(
                f"  {escape_controls(finding.path)}: {escape_controls(finding.kind)}",
                width,
                indent="    ",
            )
        out += _fold(
            "unstage the file, or add it to the ignore list, then ask again", width
        )
        return out
    count = len(request.files)
    noun = "file" if count == 1 else "files"
    out += _fold(f"secret scan: passed ({count} {noun})", width)
    out += _fold(COMMIT_CHOICES, width, indent="  ")
    return out


def branch_prompt_lines(action: str, name: str, width: int) -> list[str]:
    """A branch change (create, switch, delete): what it does, in words, then the choice."""
    out = _fold("branch (tier 2)", width, indent="  ")
    out += _fold(f"{escape_controls(action)} branch {escape_controls(name)}", width)
    out += _fold(BRANCH_CHOICES, width, indent="  ")
    return out


def worktree_prompt_lines(path: str, width: int) -> list[str]:
    out = _fold("worktree (tier 2)", width, indent="  ")
    out += _fold(f"add a worktree at {escape_controls(path)}", width)
    out += _fold(BRANCH_CHOICES, width, indent="  ")
    return out


def push_prompt_lines(remote: str, branch: str, width: int) -> list[str]:
    """A push is remote git: tier 3, and the screen names the handshake it needs."""
    out = _fold("push (tier 3, remote git)", width, indent="  ")
    out += _fold(f"push {escape_controls(branch)} to {escape_controls(remote)}", width)
    out += _fold(
        "this needs a handshake: an operator's signed approval, not a yes here alone",
        width,
    )
    out += _fold(PUSH_CHOICES, width, indent="  ")
    return out
