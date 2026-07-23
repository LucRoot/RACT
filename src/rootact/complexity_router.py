# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Complexity router for RACT inference endpoints.

Scores a task description into low/medium/high/frontier tiers and selects the
cheapest healthy endpoint from a configured 3-tier list
(local, low_cost_cloud, high_cost_fallback).  Keeps ~95% of work on local
models by default while providing explicit fallbacks for higher complexity.
"""

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class ComplexityScore:
    """Score and tier assignment for a task."""

    tier: str
    score: float
    signals: Dict[str, float] = field(default_factory=dict)


@dataclass
class EndpointSelection:
    """Selected endpoint plus routing metadata."""

    endpoint_tier: str
    endpoint: Dict[str, object]
    endpoint_name: str
    score: ComplexityScore
    healthy: bool = True


class ComplexityRouter:
    """Route tasks to the cheapest healthy endpoint by complexity tier.

    Configuration shape::

        {
            "tiers": {
                "local": {"endpoint": {"base_url": "...", "model": "..."}, "cost": 1},
                "low_cost_cloud": {"endpoint": {"base_url": "...", "model": "..."}, "cost": 5},
                "high_cost_fallback": {"endpoint": {"base_url": "...", "model": "..."}, "cost": 50},
            },
            "thresholds": {"low": 0.25, "medium": 0.55, "high": 0.80}
        }

    The default thresholds are chosen so that routine, well-bounded tasks land
    on the local tier, moderately complex tasks land on the low-cost cloud
    tier, and rare frontier tasks fall through to the high-cost fallback.
    """

    DEFAULT_THRESHOLDS = {"low": 0.30, "medium": 0.55, "high": 0.80}

    # Map score tiers (low/medium/high/frontier) to endpoint tier names in the
    # order they should be tried.  Default keeps ~95% of work on local and only
    # escalates to cloud tiers when local is unhealthy or complexity demands it.
    DEFAULT_TIER_MAP: Dict[str, List[str]] = {
        "low": ["local", "low_cost_cloud", "high_cost_fallback"],
        "medium": ["low_cost_cloud", "high_cost_fallback", "local"],
        "high": ["high_cost_fallback", "low_cost_cloud", "local"],
        "frontier": ["high_cost_fallback", "low_cost_cloud", "local"],
    }

    # Keywords that push complexity up.  Each hit contributes a meaningful
    # boost; the keyword contribution is capped so a pile of words cannot
    # trivially max out, but clear frontier signals still reach the high tier.
    COMPLEXITY_BOOSTS = {
        "refactor": 0.14,
        "architecture": 0.18,
        "design": 0.16,
        "algorithm": 0.14,
        "multiple": 0.10,
        "cross-module": 0.18,
        "repo-wide": 0.22,
        "frontier": 0.25,
        "research": 0.18,
        "novel": 0.16,
        "unknown": 0.12,
        "safety": 0.12,
        "security": 0.12,
        "compliance": 0.12,
    }

    COMPLEXITY_DAMPERS = {
        "one-line": -0.18,
        "trivial": -0.18,
        "fix typo": -0.15,
        "single file": -0.10,
        "small": -0.10,
        "cli flag": -0.10,
        "export": -0.06,
        "json output": -0.06,
        "markdown": -0.06,
    }

    def __init__(
        self,
        tiers: Optional[Dict[str, Dict[str, object]]] = None,
        thresholds: Optional[Dict[str, float]] = None,
        tier_map: Optional[Dict[str, List[str]]] = None,
        health_check_fn: Optional[Callable[[Dict[str, object]], bool]] = None,
    ) -> None:
        self.tiers = dict(tiers) if tiers else {}
        self.thresholds = dict(thresholds) if thresholds else dict(self.DEFAULT_THRESHOLDS)
        self.tier_map = dict(tier_map) if tier_map else dict(self.DEFAULT_TIER_MAP)
        self.health_check_fn = health_check_fn

    def score_task(self, task: str) -> ComplexityScore:
        """Return a complexity score and tier for ``task``."""
        text = (task or "").lower()
        score = 0.0
        signals: Dict[str, float] = {}

        # Length signal: longer, more detailed prompts tend to be harder.
        word_count = len(text.split())
        length_signal = min(word_count / 200.0, 1.0) * 0.25
        signals["length"] = length_signal
        score += length_signal

        # Keyword boosts.
        keyword_score = 0.0
        for phrase, boost in self.COMPLEXITY_BOOSTS.items():
            if phrase in text:
                keyword_score += boost
                signals[f"boost:{phrase}"] = boost
        # Cap keyword contribution so a pile of words cannot trivially max out,
        # but clear frontier signals still accumulate enough to reach high tier.
        score += min(keyword_score, 0.65)

        # Keyword dampers.
        damper_score = 0.0
        for phrase, damper in self.COMPLEXITY_DAMPERS.items():
            if phrase in text:
                damper_score += damper
                signals[f"damper:{phrase}"] = damper
        score += max(damper_score, -0.30)

        # Code fences / structured artifacts are a mild complexity signal.
        fence_count = len(re.findall(r"```", text))
        signals["fences"] = min(fence_count * 0.02, 0.08)
        score += signals["fences"]

        score = max(0.0, min(1.0, score))
        tier = self._tier_for_score(score)
        return ComplexityScore(tier=tier, score=round(score, 4), signals=signals)

    def _tier_for_score(self, score: float) -> str:
        """Map a 0-1 score to a tier name."""
        if score <= self.thresholds.get("low", 0.25):
            return "low"
        if score <= self.thresholds.get("medium", 0.55):
            return "medium"
        if score <= self.thresholds.get("high", 0.80):
            return "high"
        return "frontier"

    def _is_healthy(self, endpoint: Dict[str, object]) -> bool:
        """Return True if the endpoint passes the optional health check."""
        if self.health_check_fn is None:
            return True
        try:
            return bool(self.health_check_fn(endpoint))
        except Exception:  # noqa: BLE001 - health failure is a fallback signal
            return False

    def select_endpoint(
        self,
        task: str,
        health_check_fn: Optional[Callable[[Dict[str, object]], bool]] = None,
    ) -> EndpointSelection:
        """Select the cheapest healthy endpoint for ``task``.

        Args:
            task: Task description to score.
            health_check_fn: Optional override for the constructor health check.

        Returns:
            EndpointSelection describing the chosen tier and endpoint.

        Raises:
            ValueError: if no tiers are configured.
            RuntimeError: if no healthy endpoint is available.
        """
        if not self.tiers:
            raise ValueError("no tiers configured")

        score = self.score_task(task)
        ordered_tiers = self.tier_map.get(score.tier, list(self.tiers.keys()))
        check = health_check_fn or self.health_check_fn or (lambda _ep: True)

        for tier_name in ordered_tiers:
            tier_cfg = self.tiers.get(tier_name)
            if not tier_cfg:
                continue
            endpoint = tier_cfg.get("endpoint")
            if not isinstance(endpoint, dict):
                continue
            try:
                healthy = bool(check(endpoint))
            except Exception:  # noqa: BLE001
                healthy = False
            if healthy:
                return EndpointSelection(
                    endpoint_tier=tier_name,
                    endpoint=endpoint,
                    endpoint_name=endpoint.get("name", tier_name),
                    score=score,
                    healthy=True,
                )

        raise RuntimeError(f"no healthy endpoint available for tier {score.tier}")

    @classmethod
    def from_config(
        cls,
        config: Dict[str, object],
        health_check_fn: Optional[Callable[[Dict[str, object]], bool]] = None,
    ) -> "ComplexityRouter":
        """Build a router from a config dict."""
        tiers = config.get("tiers")
        if not isinstance(tiers, dict):
            raise ValueError("config.tiers must be a dict")
        thresholds = config.get("thresholds")
        if thresholds is not None and not isinstance(thresholds, dict):
            raise ValueError("config.thresholds must be a dict")
        tier_map = config.get("tier_map")
        if tier_map is not None and not isinstance(tier_map, dict):
            raise ValueError("config.tier_map must be a dict")
        return cls(
            tiers=tiers,
            thresholds=thresholds,
            tier_map=tier_map,
            health_check_fn=health_check_fn,
        )
