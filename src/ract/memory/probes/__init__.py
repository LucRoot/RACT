"""Self-adjustment probes package (v0.5.0 memory discipline, module_08).

Three probe suites measure provider behavior on the current provider mix:

- :mod:`~ract.memory.probes.needle` — needle-in-a-haystack recall.
- :mod:`~ract.memory.probes.coherence` — subtle-inconsistency detection.
- :mod:`~ract.memory.probes.adherence` — instruction persistence.

The :mod:`~ract.memory.probes.scheduler` runs all three, reduces the
reports into a :class:`~ract.memory.probes.scheduler.ModelCapability`
record, and writes it atomically to ``.ract/probes/capability.json``.
Budgets derive from this record when populated; the module_01 spec
defaults ship as fallback for a fresh install.

Nightly recompilation and the drift detector defer to v0.6 per master
spec §Bounded scope. DSPy signature compilation-recompilation is
deferred per ADR-0043 (no ``src/ract/compilation/`` directory; no
``dspy`` in ``pyproject.toml``); LeWM 23-dim behavioral-vector drift
detection is deferred per ADR-0044 (no ``src/ract/observability/``
package; no ``lewm.py`` / ``drift.py``). This module ships the
aggregator + a manual ``ract memory apply-narrowings`` verb the
operator triggers by hand.

Reference: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §Self-
adjustment, §Signals item 10, and ``docs/ADRs/ADR-0038-self-
adjustment-probes.md``.
"""

from __future__ import annotations

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.probes.adherence import (
    AdherenceProbe,
    AdherenceProbeReport,
)
from ract.memory.probes.coherence import (
    CoherenceProbe,
    CoherenceProbeReport,
)
from ract.memory.probes.needle import (
    NeedleProbe,
    NeedleProbeReport,
)
from ract.memory.probes.scheduler import (
    CAPABILITY_RECORD_PATH,
    ModelCapability,
    ProbeReports,
    ProbeScheduler,
    read_capability_record,
    run_all_probes,
    write_capability_record,
)


__all__ = [
    "AdherenceProbe",
    "AdherenceProbeReport",
    "CAPABILITY_RECORD_PATH",
    "CoherenceProbe",
    "CoherenceProbeReport",
    "ModelCapability",
    "NeedleProbe",
    "NeedleProbeReport",
    "ProbeReports",
    "ProbeScheduler",
    "read_capability_record",
    "run_all_probes",
    "write_capability_record",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
