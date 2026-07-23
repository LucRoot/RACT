# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""3-tier inference router for RACT.

Combines the complexity scorer with an ordered fallback chain so that
routine work stays on local inference, moderately complex work can spill to
a low-cost cloud endpoint, and rare frontier work escalates to a high-cost
fallback.  Each tier may contain multiple endpoints; the router tries them in
order and, if configured, escalates to the next tier.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from rootact.complexity_router import ComplexityRouter
from rootact.router_fallback import FallbackChain


@dataclass
class InferenceResult:
    """Result of routing a task through the 3-tier inference pipeline."""

    success: bool
    task: str = ""
    selected_tier: str = ""
    selected_endpoint: Optional[str] = None
    value: Any = None
    error: Optional[str] = None
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    cross_tier_fallback: bool = False


class InferenceRouter:
    """Route an inference request across local / cloud / frontier tiers.

    Configuration shape::

        {
            "tiers": {
                "local": {
                    "endpoints": [
                        {"name": "qwen", "base_url": "...", "model": "...",
                         "timeout": 300, "max_tokens": 2048},
                    ],
                    "cost": 1,
                },
                "low_cost_cloud": { ... },
                "high_cost_fallback": { ... },
            },
            "thresholds": {"low": 0.30, "medium": 0.55, "high": 0.80},
            "tier_map": { ... },
            "cross_tier_fallback": True,
        }

    ``call_fn`` receives the chosen endpoint dict plus any keyword arguments
    passed to ``route`` and should perform the actual inference call.
    """

    DEFAULT_TIER_MAP = ComplexityRouter.DEFAULT_TIER_MAP

    def __init__(
        self,
        config: Dict[str, Any],
        health_check_fn: Optional[Callable[[Dict[str, Any]], bool]] = None,
        call_fn: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.config = dict(config)
        self.health_check_fn = health_check_fn
        self.call_fn = call_fn
        self.cross_tier_fallback = bool(self.config.get("cross_tier_fallback", True))
        self.complexity_router = ComplexityRouter.from_config(
            self._router_config(),
            health_check_fn=health_check_fn,
        )

    def _router_config(self) -> Dict[str, Any]:
        """Build the smaller config expected by ``ComplexityRouter``."""
        tiers = self.config.get("tiers", {})
        router_tiers: Dict[str, Dict[str, Any]] = {}
        for tier_name, tier_cfg in tiers.items():
            endpoints = tier_cfg.get("endpoints", [])
            representative = dict(endpoints[0]) if endpoints else {}
            router_tiers[tier_name] = {
                "endpoint": representative,
                "cost": tier_cfg.get("cost", 1),
            }
        return {
            "tiers": router_tiers,
            "thresholds": self.config.get("thresholds"),
            "tier_map": self.config.get("tier_map"),
        }

    def _tier_endpoints(self, tier_name: str) -> List[Dict[str, Any]]:
        tier_cfg = self.config.get("tiers", {}).get(tier_name, {})
        return list(tier_cfg.get("endpoints", []))

    def _next_tiers(self, tier_name: str) -> List[str]:
        """Return the ordered fallback tiers for a selected tier."""
        tier_map = self.config.get("tier_map") or self.DEFAULT_TIER_MAP
        return list(tier_map.get(tier_name, []))

    def route(
        self,
        task: str,
        call_fn: Optional[Callable[..., Any]] = None,
        **call_kwargs: Any,
    ) -> InferenceResult:
        """Route ``task`` to the cheapest healthy endpoint and execute it.

        Args:
            task: Description used for complexity scoring.
            call_fn: Optional inference call override.
            **call_kwargs: Extra arguments forwarded to ``call_fn``.

        Returns:
            InferenceResult with the selected tier/endpoint and the model output.

        Raises:
            RuntimeError: if no endpoint succeeds and ``cross_tier_fallback`` is
            disabled or all tiers fail.
        """
        fn = call_fn or self.call_fn
        if fn is None:
            raise ValueError("call_fn must be provided to route")

        selection = self.complexity_router.select_endpoint(task)
        # selection.score.tier is the score bucket (low/medium/high/frontier);
        # tier_map maps that bucket to the endpoint tier order.
        ordered_tiers = self._next_tiers(selection.score.tier)
        all_attempts: List[Dict[str, Any]] = []
        cross_tier = False

        for tier_name in ordered_tiers:
            endpoints = self._tier_endpoints(tier_name)
            if not endpoints:
                continue

            def _make_call(endpoint: Dict[str, Any]) -> Any:
                return fn(endpoint, task=task, **call_kwargs)

            chain = FallbackChain(endpoints, call_fn=_make_call)
            result = chain.try_endpoints()
            all_attempts.extend(result.attempts)

            if result.success:
                return InferenceResult(
                    success=True,
                    task=task,
                    selected_tier=tier_name,
                    selected_endpoint=result.endpoint,
                    value=result.value,
                    attempts=all_attempts,
                    cross_tier_fallback=cross_tier,
                )

            if not self.cross_tier_fallback:
                break
            cross_tier = True

        last_error = all_attempts[-1].get("error") if all_attempts else "no endpoints configured"
        return InferenceResult(
            success=False,
            task=task,
            error=last_error,
            attempts=all_attempts,
            cross_tier_fallback=cross_tier,
        )

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        health_check_fn: Optional[Callable[[Dict[str, Any]], bool]] = None,
        call_fn: Optional[Callable[..., Any]] = None,
    ) -> "InferenceRouter":
        """Build a router from a config dict."""
        tiers = config.get("tiers")
        if not isinstance(tiers, dict):
            raise ValueError("config.tiers must be a dict")
        return cls(config, health_check_fn=health_check_fn, call_fn=call_fn)
