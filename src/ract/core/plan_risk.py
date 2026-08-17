"""Static plan-risk analyzer.

Pre-execution advisory summary computed from the plan alone. The score
is a deterministic static heuristic over declared step fields — never a
model-graded opinion — because the operator's substrate design refuses
"external reviewer as a concept" (docs/ROADMAP.md v0.5). A plan with no
destructive verbs and no tier-3 steps scores 0.0; the more high-risk
steps a plan contains, the higher the score.

The report is emitted as a ``plan.risk_assessed`` trace event by
:func:`ract.core.compile.IntentCompiler.compile` when a plan is
supplied; the ``ract plan analyze`` CLI verb reads the event out of
``evals/runs/<run_id>/events.jsonl`` and prints the report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Optional

from ract.core.module_identity import _module_knot, register_module_knot

if TYPE_CHECKING:
    from ract.core.plan import PlanSchema
    from ract.security.manifest import CapabilityManifest


RiskKind = Literal[
    "destructive",
    "irreversible",
    "high_capability_tier",
    "external_state",
]


@dataclass(frozen=True)
class HighRiskStep:
    """One flagged step in a plan-risk analysis."""

    step_id: str
    risk_kind: RiskKind
    score: float
    rationale: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "risk_kind": self.risk_kind,
            "score": self.score,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class PlanRiskReport:
    """Static advisory report over a plan's steps.

    ``risk_score`` is normalised to [0.0, 1.0] — the sum of per-step
    scores divided by (step_count or 1), then capped at 1.0. A plan
    with no flagged steps scores 0.0.
    """

    plan_id: bytes = b""
    risk_score: float = 0.0
    high_risk_steps: tuple[HighRiskStep, ...] = field(default_factory=tuple)
    suggestions: tuple[str, ...] = field(default_factory=tuple)

    def to_payload(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id.hex() if self.plan_id else "",
            "risk_score": self.risk_score,
            "high_risk_steps": [s.to_payload() for s in self.high_risk_steps],
            "suggestions": list(self.suggestions),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PlanRiskReport":
        raw_pid = str(payload.get("plan_id", ""))
        plan_id = bytes.fromhex(raw_pid) if raw_pid else b""
        return cls(
            plan_id=plan_id,
            risk_score=float(payload.get("risk_score", 0.0)),
            high_risk_steps=tuple(
                HighRiskStep(
                    step_id=str(s["step_id"]),
                    risk_kind=s["risk_kind"],
                    score=float(s["score"]),
                    rationale=str(s.get("rationale", "")),
                )
                for s in payload.get("high_risk_steps", [])
            ),
            suggestions=tuple(str(s) for s in payload.get("suggestions", [])),
        )


# ---------------------------------------------------------------------------
# Static heuristics
# ---------------------------------------------------------------------------


# Regex is anchored to word boundaries so "erase-state" matches but
# "coherent" (contains "her") does not.
_DESTRUCTIVE_WORDS = re.compile(
    r"\b(delete|remove|drop|truncate|erase|purge|destroy|rm\s+-rf|wipe)\b",
    re.IGNORECASE,
)
_IRREVERSIBLE_WORDS = re.compile(
    r"\b(publish|release|deploy|migrate|force[- ]push|commit\s+to\s+main|"
    r"rewrite\s+history|overwrite)\b",
    re.IGNORECASE,
)
_EXTERNAL_STATE_WORDS = re.compile(
    r"\b(email|send|post|charge|payment|refund|api\s+call\s+to|webhook|"
    r"third[- ]party|external\s+api)\b",
    re.IGNORECASE,
)


def _score_step_content(text: str) -> tuple[list[HighRiskStep], list[str]]:
    """Return (flags, suggestions) for one step's content text."""
    flags: list[HighRiskStep] = []
    suggestions: list[str] = []
    if _DESTRUCTIVE_WORDS.search(text):
        flags.append(
            HighRiskStep(
                step_id="",
                risk_kind="destructive",
                score=0.7,
                rationale=(
                    "step text contains destructive verbs (delete/remove/drop/…)"
                ),
            )
        )
        suggestions.append(
            "confirm destructive step is guarded by a handshake or dry-run gate"
        )
    if _IRREVERSIBLE_WORDS.search(text):
        flags.append(
            HighRiskStep(
                step_id="",
                risk_kind="irreversible",
                score=0.6,
                rationale=(
                    "step text contains irreversible verbs (publish/deploy/…)"
                ),
            )
        )
        suggestions.append(
            "verify irreversible step has an approval handshake before execution"
        )
    if _EXTERNAL_STATE_WORDS.search(text):
        flags.append(
            HighRiskStep(
                step_id="",
                risk_kind="external_state",
                score=0.5,
                rationale=(
                    "step text touches external state (email/send/api/…)"
                ),
            )
        )
        suggestions.append(
            "confirm external-state step is rate-limited and audited"
        )
    return flags, suggestions


def _step_id_for(step: Any, position: int) -> str:
    """Return a stable identifier for a plan step (works for both plan types)."""
    sid = getattr(step, "step_id", None)
    if sid:
        return str(sid)
    return f"step-{position}"


def _step_text(step: Any) -> str:
    """Return the concatenated searchable text for a step."""
    parts = [
        str(getattr(step, "action", "") or ""),
        str(getattr(step, "expected_artifact", "") or ""),
        str(getattr(step, "provider_hint", "") or ""),
    ]
    tool_call = getattr(step, "tool_call", None)
    if isinstance(tool_call, dict):
        parts.append(str(tool_call.get("tool", "")))
        parts.append(str(tool_call.get("action", "")))
    return " ".join(p for p in parts if p)


def analyze_plan(
    plan: Optional["PlanSchema"] = None,
    manifest: Optional["CapabilityManifest"] = None,
    *,
    plan_id: bytes = b"",
) -> PlanRiskReport:
    """Return the :class:`PlanRiskReport` for ``plan``.

    Uses only static heuristics — never a model-graded opinion. When a
    ``CapabilityManifest`` is supplied, the per-step scores for
    ``high_capability_tier`` are downgraded by the manifest's
    ``tiers.default`` maximum (a plan cannot cost more risk than the
    manifest already permits).
    """
    if plan is None or not getattr(plan, "steps", None):
        return PlanRiskReport(plan_id=plan_id)

    flagged: list[HighRiskStep] = []
    suggestions: list[str] = []
    seen_suggestions: set[str] = set()

    for position, step in enumerate(plan.steps):
        sid = _step_id_for(step, position)
        text = _step_text(step)
        step_flags, step_sugs = _score_step_content(text)
        for flag in step_flags:
            flagged.append(
                HighRiskStep(
                    step_id=sid,
                    risk_kind=flag.risk_kind,
                    score=flag.score,
                    rationale=flag.rationale,
                )
            )
        for sug in step_sugs:
            if sug not in seen_suggestions:
                suggestions.append(sug)
                seen_suggestions.add(sug)

        tier = str(getattr(step, "tier", "") or "").upper()
        if tier in {"T2", "T3"}:
            base_score = 0.4 if tier == "T2" else 0.9
            downgrade = 0.0
            if manifest is not None:
                default_tier = getattr(getattr(manifest, "tiers", None), "default", 3)
                if default_tier >= int(tier[1]):
                    # Manifest already permits this tier; halve the tier score.
                    downgrade = base_score / 2.0
            flagged.append(
                HighRiskStep(
                    step_id=sid,
                    risk_kind="high_capability_tier",
                    score=max(0.0, base_score - downgrade),
                    rationale=f"step declares tier {tier}",
                )
            )
            sug = (
                "verify high-tier step has a matching capability grant in the manifest"
            )
            if sug not in seen_suggestions:
                suggestions.append(sug)
                seen_suggestions.add(sug)

    if not flagged:
        return PlanRiskReport(plan_id=plan_id)

    step_count = max(1, len(plan.steps))
    raw_score = sum(f.score for f in flagged) / step_count
    normalised = min(1.0, raw_score)
    return PlanRiskReport(
        plan_id=plan_id,
        risk_score=normalised,
        high_risk_steps=tuple(flagged),
        suggestions=tuple(suggestions),
    )


__all__ = [
    "HighRiskStep",
    "PlanRiskReport",
    "RiskKind",
    "analyze_plan",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.4.1
