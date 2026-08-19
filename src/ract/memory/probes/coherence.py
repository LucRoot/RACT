"""Coherence probe (module_08 step 3).

Provides a long context with a subtle inconsistency (two mutually
contradictory statements about the same fact) and asks the model to
identify it. Measures reasoning quality at length: the largest context
size at which the model still spots the contradiction.

Design notes:

- The contradiction is a date/day pair for a single named event. Both
  the "Tuesday" and the "Wednesday" claim appear verbatim; a response
  that identifies the inconsistency must mention BOTH days (case-
  insensitive substring match). A weaker match (mentioning only one
  day) is treated as a miss because it fails to establish the model
  spotted the pair.
- Prompt construction is deterministic in ``size``: the same size
  always produces the same prompt string. Reuses the module_06 mock
  provider path (POST inbound constraint 2).
- Cliff-detection is monotonic-descending: the ``reasoning_quality
  _bound`` is the largest size at which the model still identified
  the inconsistency. A single miss at ``2000`` pins the bound to
  zero even if larger sizes coincidentally passed — a stricter rule
  than the needle probe's, chosen because a coherence miss at small
  size indicates a base failure that larger-size passes cannot
  redeem.

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
class CoherenceProbeReport:
    """Frozen report of one :class:`CoherenceProbe` run.

    ``identified_at_size`` — map from context size to a bool
    (``True`` when the response mentioned both contradictory tokens).

    ``reasoning_quality_bound`` — the largest size at which the model
    still identified the inconsistency. Zero when even the smallest
    tested size failed.
    """

    identified_at_size: dict[int, bool]
    reasoning_quality_bound: int


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


@dataclass
class CoherenceProbe:
    """Subtle-inconsistency detection probe."""

    STATEMENT_A: str = "The Rootknot working group meets on Tuesday at 3pm in Room 214."
    STATEMENT_B: str = (
        "The Rootknot working group meets on Wednesday at 3pm in Room 214."
    )
    QUESTION: str = (
        "Question: The passage above contains one subtle factual "
        "inconsistency about a recurring meeting. Identify it precisely, "
        "naming BOTH conflicting values."
    )
    TOKEN_A: str = "tuesday"
    TOKEN_B: str = "wednesday"
    CONTEXT_SIZES: tuple[int, ...] = (2000, 4000, 8000, 16000)
    FILLER_WORD: str = "filler"

    def build_prompt(self, size: int) -> str:
        """Return the prompt for one context size.

        Statement A is seated near the beginning; Statement B is
        seated near the end; the filler pads the middle. The two
        statements are separated by ``size - N`` filler words where
        ``N`` accounts for the statements + the question.
        """
        if size <= 0:
            raise ValueError(f"size must be positive; got {size!r}")
        header_words = len(self.STATEMENT_A.split())
        footer_words = len(self.STATEMENT_B.split()) + len(self.QUESTION.split())
        middle_words = max(0, size - header_words - footer_words)
        middle = " ".join([self.FILLER_WORD] * middle_words)
        parts = [self.STATEMENT_A, middle, self.STATEMENT_B, self.QUESTION]
        return "\n".join(part for part in parts if part)

    def response_identifies_inconsistency(self, response: str) -> bool:
        """True iff the response mentions BOTH conflicting tokens.

        Case-insensitive substring match on ``TOKEN_A`` AND
        ``TOKEN_B``. A response that mentions only one token misses
        because it fails to establish the model spotted the pair.
        """
        folded = (response or "").casefold()
        return self.TOKEN_A.casefold() in folded and self.TOKEN_B.casefold() in folded

    def run(
        self,
        provider: Any,
        *,
        declaration: Any | None = None,
        sink: EventSink | None = None,
    ) -> CoherenceProbeReport:
        """Run the probe across every context size."""
        active_sink = sink or NullEventSink()
        identified: dict[int, bool] = {}
        for size in self.CONTEXT_SIZES:
            prompt = self.build_prompt(size)
            start = time.monotonic()
            response = provider.send(prompt, declaration)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            hit = self.response_identifies_inconsistency(response)
            identified[size] = hit
            emit_probe_evaluated(
                active_sink,
                {
                    "probe": "coherence",
                    "size": size,
                    "hit": hit,
                    "duration_ms": elapsed_ms,
                },
            )
        bound = _reduce_reasoning_bound(identified, self.CONTEXT_SIZES)
        return CoherenceProbeReport(
            identified_at_size=identified,
            reasoning_quality_bound=bound,
        )


def _reduce_reasoning_bound(
    identified: dict[int, bool],
    sizes: tuple[int, ...],
) -> int:
    """Return the largest size at which the response still identified.

    Walks sizes in ascending order; the largest size for which every
    smaller-or-equal size also identified is the reported bound.
    """
    bound = 0
    for size in sorted(sizes):
        if identified.get(size, False):
            bound = size
        else:
            break
    return bound


__all__ = [
    "CoherenceProbe",
    "CoherenceProbeReport",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
