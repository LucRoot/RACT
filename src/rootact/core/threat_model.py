"""Threat model: capability tiers and refuse-list for tool execution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from rootact.core.types import Digest


class CapabilityTier(Enum):
    """Capability tier for a plan action or tool call."""

    TIER_0_READ = "T0"  # Read-only: file read, symbol search, git log.
    TIER_1_WRITE = "T1"  # Workspace-write: file write within workspace root.
    TIER_2_ENV = "T2"  # Environment: package install, git commit, network.
    TIER_3_EXTERNAL = "T3"  # External: shell outside sandbox, publish, rm -rf.


class PolicyDecision(Enum):
    """Authorization outcome for a classified action."""

    ALLOW = "allow"
    ALLOW_WITH_ROOTKNOT = "allow_with_rootknot"
    REQUIRE_HANDSHAKE = "require_handshake"
    REFUSE = "refuse"


# Default policy table per §6.1.
DEFAULT_POLICY: dict[CapabilityTier, PolicyDecision] = {
    CapabilityTier.TIER_0_READ: PolicyDecision.ALLOW,
    CapabilityTier.TIER_1_WRITE: PolicyDecision.ALLOW_WITH_ROOTKNOT,
    CapabilityTier.TIER_2_ENV: PolicyDecision.REQUIRE_HANDSHAKE,
    CapabilityTier.TIER_3_EXTERNAL: PolicyDecision.REFUSE,
}


# Patterns that mark a file or path as sensitive.
SENSITIVE_PATTERNS: list[str] = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
    "~/.ssh/**",
    "~/.aws/**",
    "~/.config/gcloud/**",
]


def _compile_sensitive_patterns() -> list[re.Pattern[str]]:
    """Compile glob-like sensitive patterns to regexes."""
    patterns: list[re.Pattern[str]] = []
    for pattern in SENSITIVE_PATTERNS:
        regex = pattern.replace(".", r"\.")
        regex = regex.replace("**", "<<<DOUBLESTAR>>>")
        regex = regex.replace("*", r"[^/\\]*")
        regex = regex.replace("<<<DOUBLESTAR>>>", ".*")
        regex = regex.replace("~", r"(?:/home/[^/]+|/Users/[^/]+|C:/Users/[^/\\]+)")
        patterns.append(re.compile(regex))
    return patterns


_SENSITIVE_REGEXES = _compile_sensitive_patterns()


@dataclass
class Refusal:
    """Structured record of a refused action."""

    action: str
    reason: str
    tier: CapabilityTier
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Authorization:
    """Outcome of authorizing an action."""

    decision: PolicyDecision
    tier: CapabilityTier
    refusals: list[Refusal] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.decision != PolicyDecision.REFUSE and not self.refusals


def _action_text(action: dict[str, Any] | str) -> str:
    """Extract a searchable text form of an action."""
    if isinstance(action, str):
        return action
    parts = []
    if "action" in action:
        parts.append(str(action["action"]))
    if "tool_call" in action:
        tool = action["tool_call"]
        if isinstance(tool, dict):
            parts.append(str(tool.get("name", "")))
            args = tool.get("arguments") or tool.get("args", {})
            if isinstance(args, dict):
                parts.extend(str(v) for v in args.values())
    if "expected_artifact" in action:
        parts.append(str(action["expected_artifact"]))
    return " ".join(parts)


def classify_action(action: dict[str, Any] | str) -> CapabilityTier:
    """Classify a plan action or tool call into a capability tier.

    Classification is deterministic from schema fields, not free-text parsing.
    """
    text = _action_text(action).lower()
    tool_name = ""
    if isinstance(action, dict):
        tool = action.get("tool_call")
        if isinstance(tool, dict):
            tool_name = str(tool.get("name", "")).lower()

    # Tier 3: external / destructive.
    tier3_tokens = {
        "rm -rf",
        "rm -r",
        "del /f /s",
        "rmdir /s",
        "publish",
        "pypi",
        "npm publish",
        "cargo publish",
        "curl",
        "wget",
        "ssh",
        "scp",
        "exec",
        "shell",
        "subprocess",
        "os.system",
    }
    if tool_name in {"shell", "exec", "system", "run_command"}:
        return CapabilityTier.TIER_3_EXTERNAL
    if any(token in text for token in tier3_tokens):
        return CapabilityTier.TIER_3_EXTERNAL

    # Tier 2: environment mutation.
    tier2_tokens = {
        "pip install",
        "npm install",
        "yarn install",
        "pnpm install",
        "poetry add",
        "git commit",
        "git push",
        "git merge",
        "docker",
        "network",
        "fetch",
        "http",
        "request",
    }
    if tool_name in {"install", "commit", "push", "merge", "docker_run"}:
        return CapabilityTier.TIER_2_ENV
    if any(token in text for token in tier2_tokens):
        return CapabilityTier.TIER_2_ENV

    # Tier 1: workspace write.
    tier1_tokens = {
        "write",
        "create",
        "update",
        "modify",
        "edit",
        "apply",
        "patch",
        "delete file",
        "remove file",
    }
    if tool_name in {"write_file", "apply_patch", "delete_file"}:
        return CapabilityTier.TIER_1_WRITE
    if any(token in text for token in tier1_tokens):
        return CapabilityTier.TIER_1_WRITE

    # Default to read-only.
    return CapabilityTier.TIER_0_READ


def _normalize_path(path: Path | str) -> Path:
    """Return a cleaned, absolute Path with consistent separators."""
    p = Path(path).expanduser().resolve()
    return p


def _is_within_workspace(target: Path, workspace_root: Path) -> bool:
    """Return True when target is workspace-root-relative."""
    try:
        target.relative_to(workspace_root.resolve())
        return True
    except ValueError:
        return False


def _matches_sensitive(path: Path | str) -> bool:
    """Return True if the path matches a sensitive pattern."""
    text = str(path).replace("\\", "/")
    return any(pattern.search(text) for pattern in _SENSITIVE_REGEXES)


def _is_version_controlled(path: Path) -> bool:
    """Heuristic: path is under version control if .git exists in a parent."""
    for parent in path.resolve().parents:
        if (parent / ".git").is_dir():
            return True
    return False


def _looks_like_rm_rf(text: str) -> bool:
    """Detect rm -rf / del /s style destructive commands."""
    lowered = text.lower()
    return "rm -rf" in lowered or "rm -r" in lowered or "rmdir /s" in lowered


def authorize_action(
    action: dict[str, Any] | str,
    workspace_root: Path | str,
    *,
    allow_tier_3: bool = False,
    force_overwrite_paths: set[str] | None = None,
    file_rootknot_key: Digest | None = None,
    current_session_key: Digest | None = None,
    size_bytes: int | None = None,
    chunk_threshold_bytes: int = 1024 * 1024,
) -> Authorization:
    """Return the authorization decision for an action.

    Applies the capability tier, sandbox gating, and refuse-list rules.
    """
    tier = classify_action(action)
    decision = DEFAULT_POLICY[tier]
    refusals: list[Refusal] = []
    text = _action_text(action)
    workspace = _normalize_path(workspace_root)
    force_overwrite = force_overwrite_paths or set()

    # Refuse-list checks.
    target_path_str = ""
    if isinstance(action, dict):
        for key in ("expected_artifact", "path", "file", "target"):
            if key in action and action[key]:
                target_path_str = str(action[key])
                break
        tool = action.get("tool_call")
        if isinstance(tool, dict):
            args = tool.get("arguments") or tool.get("args", {})
            if isinstance(args, dict):
                target_path_str = target_path_str or str(args.get("path", ""))

    if target_path_str:
        raw_target = Path(target_path_str)
        if raw_target.is_absolute():
            target = _normalize_path(raw_target)
        else:
            target = _normalize_path(workspace / raw_target)

        # Do not modify files outside workspace root.
        if tier in (CapabilityTier.TIER_1_WRITE, CapabilityTier.TIER_2_ENV):
            if not _is_within_workspace(target, workspace):
                refusals.append(
                    Refusal(
                        action=text,
                        reason="target path outside workspace root",
                        tier=tier,
                        details={"target": target_path_str, "workspace": str(workspace)},
                    )
                )

        # Do not read sensitive files.
        if tier == CapabilityTier.TIER_0_READ and _matches_sensitive(target):
            refusals.append(
                Refusal(
                    action=text,
                    reason="sensitive file read blocked",
                    tier=tier,
                    details={"target": target_path_str},
                )
            )

        # Do not overwrite files signed by a different session without force flag.
        if (
            tier == CapabilityTier.TIER_1_WRITE
            and file_rootknot_key is not None
            and current_session_key is not None
            and file_rootknot_key != current_session_key
            and target_path_str not in force_overwrite
        ):
            refusals.append(
                Refusal(
                    action=text,
                    reason="overwrite refused: file rootknot belongs to a different session",
                    tier=tier,
                    details={"target": target_path_str},
                )
            )

    # Tier 3 destructive commands.
    if _looks_like_rm_rf(text) and not _is_version_controlled(workspace):
        refusals.append(
            Refusal(
                action=text,
                reason="rm -rf on paths not under version control",
                tier=CapabilityTier.TIER_3_EXTERNAL,
                details={"command": text},
            )
        )

    # Publishing to package registries.
    lowered = text.lower()
    if "publish" in lowered and not allow_tier_3:
        refusals.append(
            Refusal(
                action=text,
                reason="package registry publish refused without explicit allow-tier-3",
                tier=CapabilityTier.TIER_3_EXTERNAL,
                details={"action": text},
            )
        )

    # Full-workspace upload size check.
    if size_bytes is not None and size_bytes > chunk_threshold_bytes:
        refusals.append(
            Refusal(
                action=text,
                reason="full workspace upload exceeds chunk threshold",
                tier=CapabilityTier.TIER_2_ENV,
                details={"size_bytes": size_bytes, "threshold": chunk_threshold_bytes},
            )
        )

    # Tier 3 gating.
    if tier == CapabilityTier.TIER_3_EXTERNAL:
        if allow_tier_3:
            # Even with --allow-tier-3, each action must be handshake-approved.
            decision = PolicyDecision.REQUIRE_HANDSHAKE
        elif not any(r.tier == CapabilityTier.TIER_3_EXTERNAL for r in refusals):
            refusals.append(
                Refusal(
                    action=text,
                    reason="tier 3 action refused by default",
                    tier=tier,
                    details={"allow_tier_3": False},
                )
            )

    if refusals:
        decision = PolicyDecision.REFUSE

    return Authorization(decision=decision, tier=tier, refusals=refusals)


# RACT 0.2.0
