"""Needle-in-a-haystack probe (module_08 step 2).

Inserts a specific fact at various depths in a context of increasing
size, asks a question requiring the fact, and measures recall. The
report records ``recall_at_depth`` (a nested dict keyed by depth then
size) and ``usable_context_window`` (the largest size at which every
tested depth still recalled the fact).

Design notes:

- The probe is deterministic in prompt construction: the same
  ``(depth, size)`` pair always produces the same prompt string. This
  makes probes reproducible under a canned-response provider (module_06
  POST inbound constraint 2 — reuse :class:`~ract.memory.functions.
  testing.MockProvider` for probe fixtures).
- The needle text and the question text are class attributes so a
  subclass (or a test) can inject a different pair without rewriting
  the runner.
- Recall is decided by :meth:`response_contains_needle`: the
  provider's response must contain the needle payload substring. A
  substring test tolerates minor formatting differences (quoting,
  punctuation) that a strict-equality test would fail on.
- The cliff-detection rule is conservative: a single miss at a lower
  depth pins the ``usable_context_window`` to the previous size, so
  one bad response at ``depth=0.05`` on the ``2000``-token context
  does NOT propagate a false floor upward. This closes the Second
  Pass adversarial question about cliff-detection sensitivity to
  noise (module_08.md `## Reasoning Endpoints for scoping`).

Reference: master spec §Quality probes, Greg Kamradt's public
needle-in-a-haystack benchmark shape (ADR-0038 alternatives).
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
class NeedleProbeReport:
    """Frozen report of one :class:`NeedleProbe` run.

    ``recall_at_depth`` — nested map: ``{depth: {size: bool}}``. The
    outer key is the fractional depth (0.05 / 0.25 / 0.50 / 0.75 /
    0.95); the inner key is the context size in tokens. The value is
    ``True`` when the provider's response contained the needle.

    ``usable_context_window`` — the largest context size at which
    every tested depth still recalled the needle. Zero when even the
    smallest tested size failed at some depth. This is the empirical
    upper bound the retrieval cascade budgets against.
    """

    recall_at_depth: dict[float, dict[int, bool]]
    usable_context_window: int


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


@dataclass
class NeedleProbe:
    """Needle-in-a-haystack probe (needle recall vs. depth vs. size).

    Depths ``0.05 / 0.25 / 0.50 / 0.75 / 0.95`` and context sizes
    ``2000 / 4000 / 8000 / 16000`` tokens per master spec §Quality
    probes.
    """

    NEEDLE: str = "The launch code is BLUE-42-ZULU."
    NEEDLE_ANSWER: str = "BLUE-42-ZULU"
    QUESTION: str = (
        "Question: What is the launch code exactly as written earlier "
        "in this context? Answer with the code itself and nothing else."
    )
    DEPTHS: tuple[float, ...] = (0.05, 0.25, 0.50, 0.75, 0.95)
    CONTEXT_SIZES: tuple[int, ...] = (2000, 4000, 8000, 16000)
    FILLER_WORD: str = "filler"

    def build_prompt(self, size: int, depth: float) -> str:
        """Return the prompt for one ``(depth, size)`` pair.

        The filler is a repeating single-token word, so
        ``WhitespaceTokenEstimator`` counts words 1:1 with the target
        size. Real providers see the same prompt regardless of their
        native tokenizer — the ``size`` label is the whitespace-token
        approximation, not a per-provider guarantee.
        """
        if size <= 0:
            raise ValueError(f"size must be positive; got {size!r}")
        if not (0.0 <= depth <= 1.0):
            raise ValueError(f"depth must be in [0, 1]; got {depth!r}")
        before_words = max(0, int(round((size - 1) * depth)))
        after_words = max(0, size - 1 - before_words)
        before = " ".join([self.FILLER_WORD] * before_words)
        after = " ".join([self.FILLER_WORD] * after_words)
        parts = [before, self.NEEDLE, after, self.QUESTION]
        return "\n".join(part for part in parts if part)

    def response_contains_needle(self, response: str) -> bool:
        """True iff ``response`` contains the needle answer substring.

        Case-insensitive on the payload string so a provider that
        casefolds does not lose the signal. The whole-answer form
        ``BLUE-42-ZULU`` is matched; the surrounding sentence is
        allowed to vary.
        """
        return self.NEEDLE_ANSWER.casefold() in (response or "").casefold()

    def run(
        self,
        provider: Any,
        *,
        declaration: Any | None = None,
        sink: EventSink | None = None,
    ) -> NeedleProbeReport:
        """Run the probe across every ``(depth, size)`` pair.

        ``provider.send(prompt, declaration)`` is invoked once per pair;
        the response is passed through :meth:`response_contains_needle`.
        The declaration is passed as-is so the caller can supply a
        :class:`~ract.memory.budget.BudgetDeclaration` or a stub. A
        ``probe.evaluated`` event fires per pair; the sink defaults to
        :class:`~ract.memory.events.NullEventSink`.
        """
        active_sink = sink or NullEventSink()
        recall: dict[float, dict[int, bool]] = {d: {} for d in self.DEPTHS}
        for depth in self.DEPTHS:
            for size in self.CONTEXT_SIZES:
                prompt = self.build_prompt(size, depth)
                start = time.monotonic()
                response = provider.send(prompt, declaration)
                elapsed_ms = int((time.monotonic() - start) * 1000)
                hit = self.response_contains_needle(response)
                recall[depth][size] = hit
                emit_probe_evaluated(
                    active_sink,
                    {
                        "probe": "needle",
                        "depth": depth,
                        "size": size,
                        "hit": hit,
                        "duration_ms": elapsed_ms,
                    },
                )
        usable = _reduce_usable_context_window(recall, self.CONTEXT_SIZES)
        return NeedleProbeReport(recall_at_depth=recall, usable_context_window=usable)


def _reduce_usable_context_window(
    recall: dict[float, dict[int, bool]],
    sizes: tuple[int, ...],
) -> int:
    """Return the largest size at which every depth still recalled.

    Walks sizes in ascending order; the largest size for which every
    tested depth returned ``True`` is the reported window. Zero when
    the smallest tested size already failed at some depth.
    """
    usable = 0
    for size in sorted(sizes):
        if all(recall[depth].get(size, False) for depth in recall):
            usable = size
        else:
            break
    return usable


__all__ = [
    "NeedleProbe",
    "NeedleProbeReport",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
