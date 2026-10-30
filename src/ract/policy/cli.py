"""``ract policy``: keygen, sign, status, revoke (ADR-0048 D2, D3).

LR:: Every command that touches the private key reads the passphrase at a
terminal and refuses otherwise (exit 3). The project is the folder holding
``ract.yaml`` (``--config``), or the current folder. Errors print the
problem and a hint, as the rest of the CLI does. Nothing here opens tier 3
by itself: a grant holds only when ``load_grant`` says so.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ract.policy import config_dir
from ract.policy.grant import (
    PolicyInvalid,
    load_grant,
    revoke,
    sandbox_confines_commands,
    sign,
)
from ract.policy.operator_key import (
    OperatorKeyError,
    PassphraseNeedsTerminal,
    generate,
    load_public,
    passphrase_warning,
    operator_dir,
    read_passphrase,
)
from ract.ui.tier_status_view import TierState, expiry_notice, status_line

USAGE = (
    "usage: ract policy init --guided | keygen [--rotate] | sign | status | revoke "
    "| migrate-keys [--config PATH]"
)


def tier_state(project: Path) -> tuple[TierState, str]:
    """The status-line state of *project*'s grant, and why tier 3 is off when it is."""
    return tier_state_of(load_grant(project))


def tier_state_of(state: Any) -> tuple[TierState, str]:
    """The status-line state of a grant already loaded (``load_grant``)."""
    if state.holds and state.policy is not None:
        # A grant opens "ask"; the session raises it up to max_mode on request.
        return TierState("ask", state.policy.expires_at.date()), ""
    expires = (
        state.policy.expires_at.date()
        if state.status == "expired" and state.policy is not None
        else None
    )
    return TierState("off", expires), state.reason


def _project(config: str | None) -> Path:
    return Path(config).resolve().parent if config else Path.cwd()


def _fail(exc: OperatorKeyError | PolicyInvalid) -> int:
    if isinstance(exc, PolicyInvalid):
        for problem in exc.problems:
            print(problem)
        print("hint: fix .ract/policy.yaml, then run `ract policy sign` again")
        return 2
    print(f"error: {exc}")
    print(f"hint: {exc.hint}")
    return 3 if isinstance(exc, PassphraseNeedsTerminal) else 2


def _keygen(rotate: bool) -> int:
    try:
        passphrase = read_passphrase(
            "New passphrase (8 characters or more, 12 is better): ", confirm=True
        )
        key = generate(passphrase, rotate=rotate)
        warning = passphrase_warning(passphrase)
        if warning:
            print(warning)
    except OperatorKeyError as exc:
        return _fail(exc)
    print(f"operator key {key.key_id} created in {operator_dir()}")
    print(f"public key pinned in {config_dir() / 'config.yaml'}")
    if rotate:
        print(
            "grants signed with the old key no longer hold: run `ract policy sign` in each"
        )
    return 0


def _sign(project: Path) -> int:
    if not (project / ".ract" / "policy.yaml").is_file():
        print("error: there is no .ract/policy.yaml to sign")
        print("hint: `ract policy init --guided` writes one for this project")
        return 2
    from ract.policy.grant import parse_policy
    from ract.policy.unlock import SESSION_WINDOW, window_minutes

    try:
        key = load_public()
        text = (project / ".ract" / "policy.yaml").read_text(encoding="utf-8")
        sandbox = parse_policy(text).sandbox
        private = SESSION_WINDOW.signing_key(
            read_passphrase, minutes=window_minutes(sandbox)
        )
        digest = sign(project, private, key)
    except (OperatorKeyError, PolicyInvalid) as exc:
        return _fail(exc)
    print(f"signed .ract/policy.yaml with {key.key_id} (sha256 {digest[:12]})")
    state = load_grant(project)
    print(
        f"tier 3: {status_line(tier_state(project)[0])}"
        + (f" ({state.reason})" if state.reason else "")
    )
    return 0


def permission_lines(project: Path) -> list[str]:
    """The tier-3 part of ``/permissions``: the grant's state and what it allows (B-111)."""
    from ract.policy.unlock import SESSION_WINDOW

    state = load_grant(project)
    tier, why = tier_state(project)
    # A grant that exists and does not hold is not "no grant": say its reason.
    lines = [
        f"Tier 3: off: {why}"
        if why and why != "no grant" and tier.grant_expires is None
        else f"Tier 3: {status_line(tier)}"
    ]
    if state.holds and state.policy is not None:
        policy = state.policy
        lines.append(
            f"Grant signed by {policy.key_id}, max mode {policy.max_mode}, "
            f"expires {policy.expires_at.date().isoformat()}."
        )
        for rule in policy.commands.allow:
            net = "network on" if rule.network else "network off"
            lines.append(
                f"  allow {rule.id}: {' '.join(rule.argv)} ({net}, {rule.timeout_s} s)"
            )
        for rule in policy.commands.deny:
            lines.append(f"  deny: {' '.join(rule.argv)}")
    else:
        lines.append("`ract policy init --guided` proposes and signs a first grant.")
    # Always said, grant or not: what the machine does, not what a grant hopes.
    lines.append(
        "Sandbox: best_effort: not enforced on this machine; commands are not confined."
        if not sandbox_confines_commands()
        else "Sandbox: enforced: commands are confined to what their rule allows."
    )
    lines.append(
        "Signing key: unlocked in memory; /permissions lock closes it."
        if SESSION_WINDOW.is_open
        else "Signing key: locked; signing asks for the passphrase."
    )
    return lines


def _status(project: Path) -> int:
    state = load_grant(project)
    tier, why = tier_state(project)
    print(
        status_line(tier) + (f": {why}" if why and tier.grant_expires is None else "")
    )
    if state.policy is not None and state.holds:
        policy = state.policy
        print(
            f"grant {state.digest[:12] if state.digest else ''} signed by {policy.key_id}"
        )
        print(
            f"max mode: {policy.max_mode}; expires {policy.expires_at.date().isoformat()}"
        )
        if policy.sandbox == "best_effort":
            print("sandbox: best_effort (commands are not confined on this machine)")
        else:
            print("sandbox: enforced")
        for rule in policy.commands.allow:
            net = "network on" if rule.network else "network off"
            print(
                f"  allow {rule.id}: {' '.join(rule.argv)} ({net}, {rule.timeout_s} s)"
            )
        for rule in policy.commands.deny:
            print(f"  deny: {' '.join(rule.argv)}")
    for problem in state.problems:
        print(f"  {problem}")
    from datetime import date

    notice = expiry_notice(tier, date.today())
    if notice:
        print(notice)
    return 0


def _init(project: Path, guided: bool) -> int:
    import shutil
    import sys

    from ract.cell_wrap import wrap_cells
    from ract.console_interrupt import read_line
    from ract.policy.guided import guided_init

    if not guided:
        print("error: `ract policy init` asks its questions with --guided")
        print("hint: run `ract policy init --guided` at a terminal")
        return 2
    if not (sys.stdin is not None and sys.stdin.isatty()):
        print(
            "error: the guided grant asks you at a terminal, and this stdin is not one"
        )
        print(
            "hint: run it in a terminal; the signing passphrase is never read from a pipe"
        )
        return 3
    width = max(40, min(80, shutil.get_terminal_size((80, 24)).columns))

    def show(line: str) -> None:
        for part in wrap_cells(line, width) or [""]:
            print(part)

    def ask(question: str) -> str | None:
        try:
            return read_line(question)
        except EOFError:
            return None

    try:
        return guided_init(
            project, ask=ask, show=show, read_passphrase=read_passphrase, width=width
        )
    except (OperatorKeyError, PolicyInvalid) as exc:
        return _fail(exc)


def _revoke(project: Path) -> int:
    digest = revoke(project)
    if digest is None:
        print("nothing to revoke: there is no .ract/policy.yaml")
        return 0
    print(
        f"revoked the grant {digest[:12]}: its signature is deleted and its digest is listed"
    )
    print("a copy restored from git history stays refused on this machine")
    return 0


def _migrate_keys(project: Path) -> int:
    """Move this project's keys out of ``.ract/`` (B-111, ADR-0048 R3)."""
    from ract.key_paths import migrate

    lines = migrate(project)
    for line in lines or ["nothing to move: no key is kept inside this project"]:
        print(line)
    return 1 if any(line.startswith("left ") for line in lines) else 0


def policy_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ract policy", add_help=True)
    parser.add_argument(
        "action",
        choices=["init", "keygen", "sign", "status", "revoke", "migrate-keys"],
    )
    parser.add_argument(
        "--rotate", action="store_true", help="replace the operator key"
    )
    parser.add_argument(
        "--guided", action="store_true", help="propose, explain and sign a first grant"
    )
    parser.add_argument("--config", default=None, help="the project's ract.yaml")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    if args.rotate and args.action != "keygen":
        print("error: --rotate belongs to `ract policy keygen`")
        print(USAGE)
        return 2
    if args.guided and args.action != "init":
        print("error: --guided belongs to `ract policy init`")
        print(USAGE)
        return 2
    project = _project(args.config)
    if args.action == "init":
        return _init(project, args.guided)
    if args.action == "migrate-keys":
        return _migrate_keys(project)
    if args.action == "keygen":
        return _keygen(args.rotate)
    if args.action == "sign":
        return _sign(project)
    if args.action == "status":
        return _status(project)
    return _revoke(project)


__all__ = ["permission_lines", "policy_command", "tier_state"]
