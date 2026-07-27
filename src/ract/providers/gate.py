"""Router gate — refuses providers without a recent passing report.

SUBSTRATE §5.4. ``ProviderRouter.register`` (v0.3 baseline) accepts any
configured slot; this gate wraps registration with a check against the
latest ``evals/conformance/results/<provider>-*.json`` report card and
refuses the provider if the report is missing, stale, or below any
category threshold.

Thresholds ship at the module_04 plan defaults; ``ract.yaml`` can
override them per-project.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_MAX_AGE_DAYS: int = 14
DEFAULT_SCHEMA_COMPLIANCE_THRESHOLD: float = 0.90
DEFAULT_TOOL_DISCIPLINE_THRESHOLD: float = 0.95
DEFAULT_REFUSAL_FIDELITY_THRESHOLD: float = 1.00
# ALM module_04: providers below this on the anti-lazy conformance
# corpus are refused for both primary and companion roles.
DEFAULT_ANTI_LAZY_CONFORMANCE_THRESHOLD: float = 0.70


@dataclass(frozen=True)
class GateConfig:
    """Router-gate thresholds. Configurable via ``ract.yaml``."""

    max_age_days: int = DEFAULT_MAX_AGE_DAYS
    schema_compliance: float = DEFAULT_SCHEMA_COMPLIANCE_THRESHOLD
    tool_discipline: float = DEFAULT_TOOL_DISCIPLINE_THRESHOLD
    refusal_fidelity: float = DEFAULT_REFUSAL_FIDELITY_THRESHOLD
    # ALM module_04 addition — providers below this on the anti-lazy
    # conformance corpus are refused for both primary and companion
    # roles. The category is optional in reports produced before ALM
    # was released; a missing category is treated as "not scored" and
    # does not cause the gate to refuse.
    anti_lazy_conformance: float = DEFAULT_ANTI_LAZY_CONFORMANCE_THRESHOLD


@dataclass(frozen=True)
class GateOutcome:
    """Result of a router-gate check."""

    admitted: bool
    reason: str = ""
    report_path: Path | None = None
    report: dict[str, Any] | None = None


def _latest_report(results_root: Path, provider: str) -> Path | None:
    if not results_root.is_dir():
        return None
    candidates = sorted(results_root.glob(f"{provider}-*.json"))
    if not candidates:
        return None
    return candidates[-1]


def _age_days(timestamp: str, now: _dt.datetime) -> float:
    parsed = _dt.datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    delta = now - parsed
    return delta.total_seconds() / 86400.0


def check_provider_gate(
    provider_name: str,
    *,
    results_root: Path,
    config: GateConfig | None = None,
    now: _dt.datetime | None = None,
) -> GateOutcome:
    """Return whether ``provider_name`` is admitted by the gate.

    Failure reasons name the missing report / stale timestamp /
    below-threshold category so the operator can act.
    """
    cfg = config or GateConfig()
    when = now or _dt.datetime.now(tz=_dt.timezone.utc)
    report_path = _latest_report(results_root, provider_name)
    if report_path is None:
        return GateOutcome(
            admitted=False,
            reason=(
                f"no conformance report for provider {provider_name!r} under "
                f"{results_root}. Run: ract conformance run --provider "
                f"{provider_name}"
            ),
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    ts = str(report.get("timestamp", ""))
    if not ts:
        return GateOutcome(
            admitted=False,
            reason=f"report {report_path} is missing 'timestamp'",
            report_path=report_path,
            report=report,
        )
    age = _age_days(ts, when)
    if age > cfg.max_age_days:
        return GateOutcome(
            admitted=False,
            reason=(
                f"report {report_path.name} is {age:.1f} days old; "
                f"gate max_age_days={cfg.max_age_days}"
            ),
            report_path=report_path,
            report=report,
        )
    categories = report.get("categories", {})
    required_thresholds = {
        "schema_compliance": cfg.schema_compliance,
        "tool_discipline": cfg.tool_discipline,
        "refusal_fidelity": cfg.refusal_fidelity,
    }
    for name, floor in required_thresholds.items():
        cat = categories.get(name)
        if not isinstance(cat, dict):
            return GateOutcome(
                admitted=False,
                reason=f"report {report_path.name} missing category {name!r}",
                report_path=report_path,
                report=report,
            )
        score = float(cat.get("score", 0.0))
        if score < floor:
            return GateOutcome(
                admitted=False,
                reason=(
                    f"provider {provider_name!r} {name} score {score:.3f} "
                    f"< threshold {floor:.3f} (report {report_path.name})"
                ),
                report_path=report_path,
                report=report,
            )
    # ALM module_04 anti-lazy threshold — optional (missing category
    # in older reports is a pass with a "not scored" reason recorded).
    al_cat = categories.get("anti_lazy")
    if isinstance(al_cat, dict) and "score" in al_cat:
        al_score = float(al_cat.get("score", 0.0))
        if al_score < cfg.anti_lazy_conformance:
            return GateOutcome(
                admitted=False,
                reason=(
                    f"provider {provider_name!r} anti_lazy score "
                    f"{al_score:.3f} < threshold "
                    f"{cfg.anti_lazy_conformance:.3f} (report "
                    f"{report_path.name})"
                ),
                report_path=report_path,
                report=report,
            )
    return GateOutcome(
        admitted=True,
        reason=f"admitted from {report_path.name}",
        report_path=report_path,
        report=report,
    )


__all__ = [
    "DEFAULT_ANTI_LAZY_CONFORMANCE_THRESHOLD",
    "DEFAULT_MAX_AGE_DAYS",
    "DEFAULT_REFUSAL_FIDELITY_THRESHOLD",
    "DEFAULT_SCHEMA_COMPLIANCE_THRESHOLD",
    "DEFAULT_TOOL_DISCIPLINE_THRESHOLD",
    "GateConfig",
    "GateOutcome",
    "check_provider_gate",
]


# RACT 0.4.0
