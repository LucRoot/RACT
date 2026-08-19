"""Adherence probe (module_08 step 4).

Provides a long context with a specific instruction seated at the
beginning, then asks a question at the end whose valid answer requires
the model to still be honoring the instruction. Measures instruction
persistence: the largest context size at which the model still followed
the instruction.

Design notes:

- The instruction is "prefix every answer with ``CROW:``". It is
  seated verbatim at the top of the prompt; the question is seated at
  the very end. A valid response starts with the prefix (case-
  sensitive; a lowercased prefix is treated as a miss because
  instruction persistence includes preservation of casing).
- Prompt construction is deterministic in ``size``. Reuses the
  module_06 mock provider path (POST inbound constraint 2).
- Cliff-detection is monotonic-descending (same rule as coherence):
  the ``persistence_bound`` is the largest size at which every
  smaller-or-equal size also honored the instruction.

Reference: master spec §Quality probes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.events import EventSink, NullEventSink, emit_probe_evaluated


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdherenceProbeReport:
    """Frozen report of one :class:`AdherenceProbe` run.

    ``instruction_persistence_at_size`` — map from context size to a
    bool (``True`` when the response honored the seated instruction).

    ``persistence_bound`` — the largest size at which the model still
    obeyed the instruction. Zero when even the smallest tested size
    failed.
    """

    instruction_persistence_at_size: dict[int, bool]
    persistence_bound: int


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


@dataclass
class AdherenceProbe:
    """Instruction persistence probe."""

    INSTRUCTION: str = (
        "INSTRUCTION: For every answer you produce in the remainder of "
        "this exchange, prefix your answer with the exact literal token "
        "CROW: (five characters: C, R, O, W, colon). Do not deviate."
    )
    EXPECTED_PREFIX: str = "CROW:"
    QUESTION: str = (
        "Question: What is two plus two? Reply with the number and "
        "nothing else besides the required prefix."
    )
    CONTEXT_SIZES: tuple[int, ...] = (2000, 4000, 8000, 16000)
    FILLER_WORD: str = "filler"

    def build_prompt(self, size: int) -> str:
        """Return the prompt for one context size."""
        if size <= 0:
            raise ValueError(f"size must be positive; got {size!r}")
        header_words = len(self.INSTRUCTION.split())
        footer_words = len(self.QUESTION.split())
        middle_words = max(0, size - header_words - footer_words)
        middle = " ".join([self.FILLER_WORD] * middle_words)
        parts = [self.INSTRUCTION, middle, self.QUESTION]
        return "\n".join(part for part in parts if part)

    def response_honors_instruction(self, response: str) -> bool:
        """True iff ``response`` starts with the required prefix.

        Case-sensitive: a lowercased ``crow:`` is a miss because
        instruction persistence includes preservation of casing (the
        instruction names the exact literal token).
        """
        return (response or "").lstrip().startswith(self.EXPECTED_PREFIX)

    def run(
        self,
        provider: Any,
        *,
        declaration: Any | None = None,
        sink: EventSink | None = None,
    ) -> AdherenceProbeReport:
        """Run the probe across every context size."""
        active_sink = sink or NullEventSink()
        persistence: dict[int, bool] = {}
        for size in self.CONTEXT_SIZES:
            prompt = self.build_prompt(size)
            start = time.monotonic()
            response = provider.send(prompt, declaration)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            hit = self.response_honors_instruction(response)
            persistence[size] = hit
            emit_probe_evaluated(
                active_sink,
                {
                    "probe": "adherence",
                    "size": size,
                    "hit": hit,
                    "duration_ms": elapsed_ms,
                },
            )
        bound = _reduce_persistence_bound(persistence, self.CONTEXT_SIZES)
        return AdherenceProbeReport(
            instruction_persistence_at_size=persistence,
            persistence_bound=bound,
        )


def _reduce_persistence_bound(
    persistence: dict[int, bool],
    sizes: tuple[int, ...],
) -> int:
    """Return the largest size at which the model still honored.

    Same monotonic-descending rule as
    :func:`ract.memory.probes.coherence._reduce_reasoning_bound`.
    """
    bound = 0
    for size in sorted(sizes):
        if persistence.get(size, False):
            bound = size
        else:
            break
    return bound


__all__ = [
    "AdherenceProbe",
    "AdherenceProbeReport",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
