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


def _other_backends() -> dict[str, str]:
    from ract.security.other_backends import why_not_wired

    return {
        name: f"named by a rule, not run yet: {why_not_wired(name)}"
        for name in ("wsl2", "container")
    }


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
    fixes: list[tuple[str, str]] = []  # (problem, command)
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
        fixes.append(
            (
                f"the grant is {state.status}",
                _FIX.get(state.status, "ract policy status"),
            )
        )
    try:
        key = load_public()
        operator_key = {"present": True, "key_id": key.key_id}
    except NoOperatorKey:
        operator_key = {"present": False, "key_id": None}
        fixes.append(
            (
                "there is no operator key",
                "ract policy keygen  (or ract policy init --guided, which makes one)",
            )
        )
    operator_key["where"] = str(operator_dir())
    operator_key["protection"] = protection()
    if (
        operator_key["present"]
        and grant["signed_by"]
        and grant["signed_by"] != operator_key["key_id"]
    ):
        fixes.append(
            ("the grant names another key than this machine's", "ract policy sign")
        )

    from ract.cli import sandbox_report

    sandbox = sandbox_report()
    record = None
    if state.digest:
        path = allowlist._record_path(project, state.digest)
        record = {"recorded": path.is_file(), "where": str(path)}
        if state.holds and not path.is_file():
            fixes.append(
                (
                    "the entry points are not recorded, so every command asks",
                    "ract policy sign",
                )
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
        # B-028: the other backends a rule may name, and why they do not run yet.
        "other_backends": _other_backends(),
        "session_mode": (
            "no session here; a session starts in ask, and /permissions allowlist "
            f"raises it up to the grant's max_mode ({grant['max_mode'] or 'none'})"
        ),
        "tools": _tools(policy, state.holds),
        "next": [command for _problem, command in fixes],
        "problems": [{"problem": p, "command": c} for p, c in fixes],
    }


def tier3_lines(report: dict[str, Any], width: int = 80) -> list[str]:
    """The report as text: MASON's screen (``ui/tier3_report.py``) says it in words."""
    from ract.ui.tier3_report import GrantFacts, Tier3Facts, tier3_report_lines

    grant = report["grant"]
    key = report["operator_key"]
    sandbox = report["sandbox"]
    entry = report["entry_points"]
    tools = report["tools"]
    facts = Tier3Facts(
        grant=GrantFacts(
            found=grant["found"],
            signed_by=grant["signed_by"] or "",
            expires=grant["expires"] or "",
            digest=grant["digest"] or "",
        ),
        why_off=report["off_because"],
        key_present=key["present"],
        key_location=key["where"],
        key_protection=key["protection"],
        window=f"{report['unlock_window']} (it lives inside a session)",
        sandbox_backend=f"{sandbox['backend']} ({sandbox['tier3_commands']})",
        sandbox_confines="; ".join(f"{k} {v}" for k, v in sandbox["confines"].items())
        or "nothing on this machine",
        sandbox_does_not="; ".join(sandbox["not_enforced"]) or "nothing listed",
        entry_point_record=(
            "none (there is no grant)"
            if entry is None
            else "recorded for this grant"
            if entry["recorded"]
            else "not recorded for this grant; every command asks"
        ),
        session_mode=report["session_mode"],
        tools_available=tuple(
            n for n, how in tools.items() if how.startswith("available")
        ),
        tools_unavailable=tuple(
            f"{n} ({how.removeprefix('not available: ')})"
            for n, how in tools.items()
            if not how.startswith("available")
        ),
        next_steps=tuple((p["problem"], p["command"]) for p in report["problems"]),
        notes=[
            f"backend {n}: {how}" for n, how in report.get("other_backends", {}).items()
        ],
    )
    return tier3_report_lines(facts, width)


__all__ = ["tier3_lines", "tier3_report"]
