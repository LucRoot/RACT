"""``ract doctor --tier3``: one report of the tier-3 state, and the next command for each problem (B-147).

LR:: A user who wonders why tier 3 is off, or what a command would do, had
to read ``ract policy status``, ``ract doctor --sandbox`` and
``/permissions`` and put them together. This module gathers the same facts
in one dict (``--json``) and one folded text: the grant, why tier 3 is off,
the operator key, the unlock window, the sandbox, the entry-point record,
the session mode, the tools the grant makes available, and for each problem
the exact command that fixes it. It reads only; it signs, runs and changes
nothing.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

# The command that fixes each grant state (ADR-0048 D3).
_FIX = {
    "none": "ract policy init --guided",
    "unsigned": "ract policy sign",
    "invalid": "fix .ract/policy.yaml as `ract policy status` says, then ract policy sign",
    "not-yet": "check this machine's clock, or wait until the grant's issue time",
    "expired": "ract policy sign  (renews it for 30 days)",
    "revoked": "ract policy init --guided  (a revoked grant is never accepted again)",
    # A session suspends a grant whose files changed under it.
    "suspended": "/permissions resume  (in the session: shows what changed and asks)",
}

# Which grant field each tier-3 tool needs, beyond a grant that holds.
_VERIFIER_KINDS = {
    "run_tests": "tests",
    "run_build": "build",
    "run_lint": "lint",
    "run_typecheck": "typecheck",
    "run_format": "format",
}


def _tools(policy: Any, holds: bool) -> dict[str, str]:
    """Each tier-3 tool: "available" or why not, for this grant."""
    from ract.core.threat_model import CapabilityTier
    from ract.tools import REGISTRY
    from ract.tools.tests_tool import _test_rule
    from ract.tools.verifier_tools import rule_for

    out: dict[str, str] = {}
    for name, spec in sorted(REGISTRY.items()):
        if spec.tier is not CapabilityTier.TIER_3_EXTERNAL:
            continue
        if not holds or policy is None:
            out[name] = "not available: tier 3 is off"
        elif name in _VERIFIER_KINDS:
            kind = _VERIFIER_KINDS[name]
            # The same lookup each tool makes when it runs.
            found = (
                _test_rule(policy) is not None
                if name == "run_tests"
                else rule_for(policy, kind) is not None
            )
            out[name] = (
                "available (asks before it runs)"
                if found
                else f"not available: no {kind} rule; ract policy add-rule {kind} -- <command>"
            )
        elif name == "web_fetch":
            fetch = getattr(policy.network_tools, "web_fetch", None)
            out[name] = (
                "available (asks before every fetch)"
                if fetch is not None and getattr(fetch, "allow_domains", None)
                else "not available: the grant names no network_tools.web_fetch.allow_domains"
            )
        elif name == "web_search":
            out[name] = "not available: no search provider is configured"
        else:
            out[name] = "available (asks, and needs its own rule or handshake)"
    return out


def tier3_report(project: Path) -> dict[str, Any]:
    """Every fact the report shows, as plain data (``--json`` prints it)."""
    from ract.policy import allowlist
    from ract.policy.grant import load_grant
    from ract.policy.operator_key import (
        NoOperatorKey,
        load_public,
        operator_dir,
        protection,
    )
    from ract.policy.unlock import SESSION_WINDOW

    project = Path(project)
    state = load_grant(project)
    policy = state.policy
    fixes: list[str] = []
    grant: dict[str, Any] = {
        "found": (project / ".ract" / "policy.yaml").is_file(),
        "status": state.status,
        "holds": state.holds,
        "signed_by": getattr(policy, "key_id", None),
        "expires": policy.expires_at.date().isoformat() if policy is not None else None,
        "digest": (state.digest or "")[:12] or None,
        "max_mode": getattr(policy, "max_mode", None),
    }
    off_because = "" if state.holds else (state.reason or state.status)
    if not state.holds:
        fixes.append(_FIX.get(state.status, "ract policy status"))
    try:
        key = load_public()
        operator_key = {"present": True, "key_id": key.key_id}
    except NoOperatorKey:
        operator_key = {"present": False, "key_id": None}
        fixes.append(
            "ract policy keygen  (or ract policy init --guided, which makes one)"
        )
    operator_key["where"] = str(operator_dir())
    operator_key["protection"] = protection()
    if (
        operator_key["present"]
        and grant["signed_by"]
        and grant["signed_by"] != operator_key["key_id"]
    ):
        fixes.append(
            "ract policy sign  (the grant names another key than this machine's)"
        )

    from ract.cli import sandbox_report

    sandbox = sandbox_report()
    record = None
    if state.digest:
        path = allowlist._record_path(project, state.digest)
        record = {"recorded": path.is_file(), "where": str(path)}
        if state.holds and not path.is_file():
            fixes.append(
                "ract policy sign  (records the entry points; until then every "
                "command asks)"
            )
    return {
        "project": str(project),
        "tier3": "on (ask)" if state.holds else "off",
        "off_because": off_because,
        "grant": grant,
        "operator_key": operator_key,
        "unlock_window": "open" if SESSION_WINDOW.is_open else "locked",
        "sandbox": {
            "tier3_commands": sandbox["tier3_commands"],
            "backend": sandbox["backend"],
            "confines": sandbox["confines"],
            "not_enforced": sandbox["not_enforced"],
        },
        "entry_points": record,
        "session_mode": (
            "no session here; a session starts in ask, and /permissions allowlist "
            f"raises it up to the grant's max_mode ({grant['max_mode'] or 'none'})"
        ),
        "tools": _tools(policy, state.holds),
        "next": fixes,
    }


def tier3_lines(report: dict[str, Any], width: int = 80) -> list[str]:
    """The report as text, every line folded to *width* columns."""
    from ract.session_events import safe_text

    grant = report["grant"]
    rows = [f"tier 3: {report['tier3']}"]
    if report["off_because"]:
        rows.append(f"  why it is off: {report['off_because']}")
    if grant["found"]:
        rows.append(
            f"grant: {grant['status']}, signed by {grant['signed_by'] or 'nobody'}, "
            f"expires {grant['expires'] or 'unknown'}, digest {grant['digest'] or 'none'}, "
            f"largest mode {grant['max_mode'] or 'none'}"
        )
    else:
        rows.append("grant: none in .ract/policy.yaml")
    key = report["operator_key"]
    rows.append(
        f"operator key: {key['key_id']} in {key['where']}"
        if key["present"]
        else f"operator key: none on this machine ({key['where']})"
    )
    rows.append(f"  {key['protection']}")
    rows.append(f"unlock window: {report['unlock_window']} (it lives inside a session)")
    sandbox = report["sandbox"]
    rows.append(f"sandbox: {sandbox['tier3_commands']} (backend {sandbox['backend']})")
    for what, how in sandbox["confines"].items():
        rows.append(f"  confines {what}: {how}")
    for item in sandbox["not_enforced"]:
        rows.append(f"  not enforced: {item}")
    entry = report["entry_points"]
    if entry is not None:
        rows.append(
            "entry points: recorded for this grant"
            if entry["recorded"]
            else "entry points: not recorded for this grant; every command asks"
        )
    rows.append(f"session mode: {report['session_mode']}")
    rows.append("tools:")
    for name, how in report["tools"].items():
        rows.append(f"  {name}: {how}")
    if report["next"]:
        rows.append("next:")
        rows += [f"  {fix}" for fix in report["next"]]
    else:
        rows.append("next: nothing to fix")
    out: list[str] = []
    for row in rows:
        indent = " " * (len(row) - len(row.lstrip(" ")))
        out += textwrap.wrap(
            safe_text(row),
            width=width,
            subsequent_indent=indent + "  ",
            break_long_words=True,
            break_on_hyphens=False,
        ) or [""]
    return out


__all__ = ["tier3_lines", "tier3_report"]
