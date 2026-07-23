"""RootAct core primitives."""

from rootact.core.assumption_registry import AssumptionRegistry, bind_assumption

__all__ = ["AssumptionRegistry", "bind_assumption"]

# Concrete reference so static reachability tooling sees the dependency.
_CORE_EXPORTS = (AssumptionRegistry, bind_assumption)

# RACT 0.2.0
