"""Sycophancy circuit breaker — reversal-scan over the event trace.

ALM §4. The scanner reads the event log for pairs of assistant turns
where the stated position changed within ``window`` turns without
intervening evidence (predicate evaluation, tool result, companion
response, or Investigator report). Suspicious reversals fire a forcing
prompt that asks the model to produce evidence or restore the prior
position; unresolved suspicious reversals taint the run and flip the
rootknot's ``reversal_taint`` to ``"partial"``.

The classifier is deterministic (regex plus a small heuristic ledger)
rather than model-based. A model-based classifier grades its own
homework, which defeats the point (Lateral Chain branch A). False
positives are handled by requiring TWO consecutive suspicious reversals
before the forcing prompt fires, and by exempting reversals inside a
documented Investigator-report event chain.

Reference sources:

- ALM spec §4 (Sycophancy Circuit Breaker) and §13 signal 9.
- ``ract.trace.events`` for the event vocabulary this reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Literal, Protocol

if TYPE_CHECKING:
    from ract.trace.events import Event


class _RepairIntentSink(Protocol):
    """Structural type for the object ``force_evidence_or_restore`` writes to.

    The substrate ``LoopController`` exposes ``_repair_intent`` as its
    next-planning-turn hook. Any object with the same settable attribute
    satisfies this Protocol; the sycophancy circuit does not import the
    controller directly so the trace layer stays free of ALM-layer
    dependencies at import time. Named with a leading underscore to mark
    it as an internal contract rather than a public API.
    """

    _repair_intent: str | None


# ---------------------------------------------------------------------------
# Position vocabulary (deterministic regex ledger)
# ---------------------------------------------------------------------------


# The ledger is intentionally shallow. It maps a small set of position
# shapes to a stable label; two adjacent labels count as a change when
# they are distinct (except the ``None`` fallback, which never triggers
# a reversal on its own). The reviewer's Q2 will surface the false-
# negative rate this leaves on the table; the module_05 Second Pass
# results section records the answer.
_POSITION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "affirm",
        re.compile(
            r"\b(yes|correct|confirmed|works|passes|done|complete(?:d)?|"
            r"success(?:ful)?|approved?|good\s+to\s+(?:go|ship)|"
            r"look(?:s)?\s+(?:good|right))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "deny",
        re.compile(
            r"\b(no|incorrect|wrong|fail(?:s|ed|ing)?|broken|"
            r"cannot|can'?t|won'?t|blocked|reject(?:ed)?|"
            r"unable|not\s+(?:working|ready|complete|correct))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "reconsider",
        re.compile(
            r"\b(actually|wait|reconsider|on\s+second\s+thought|"
            r"i\s+was\s+wrong|let\s+me\s+revise|scratch\s+that|"
            r"revised|reversing|change\s+of\s+plan)\b",
            re.IGNORECASE,
        ),
    ),
)


PositionLabel = Literal["affirm", "deny", "reconsider", "unknown"]


def _classify_position(text: str) -> PositionLabel:
    """Return the position label the regex ledger matches for ``text``.

    Returns ``"unknown"`` when no pattern matches. A ``reconsider`` hit
    always wins over ``affirm`` / ``deny`` when both fire — it is a
    stronger signal that a change is in progress.
    """
    if not text:
        return "unknown"
    hits: dict[str, bool] = {}
    for label, pattern in _POSITION_PATTERNS:
        if pattern.search(text):
            hits[label] = True
    if hits.get("reconsider"):
        return "reconsider"
    if hits.get("deny") and not hits.get("affirm"):
        return "deny"
    if hits.get("affirm") and not hits.get("deny"):
        return "affirm"
    return "unknown"


# ---------------------------------------------------------------------------
# ReversalReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReversalReport:
    """A single position-change episode surfaced by ``scan_trace``.

    ``position_1_event_id`` and ``position_2_event_id`` are the raw
    16-byte ids of the two assistant turns. ``position_1_label`` and
    ``position_2_label`` are the classifier's stable labels for those
    turns. ``intervening_evidence_events`` is the tuple of ids for
    events of the accepted evidence kinds that landed between the two
    turns (empty when the reversal is suspicious).

    ``is_suspicious`` is ``True`` when the labels differ AND no
    intervening evidence was found AND the pair is not inside an
    Investigator-report chain (see ``scan_trace``).
    """

    position_1_event_id: bytes
    position_2_event_id: bytes
    position_1_label: PositionLabel
    position_2_label: PositionLabel
    intervening_evidence_events: tuple[bytes, ...]
    is_suspicious: bool


# ---------------------------------------------------------------------------
# scan_trace — the reversal detector
# ---------------------------------------------------------------------------


# The evidence kinds that "absorb" a reversal — landing between two
# assistant turns with different positions means the model actually saw
# something new before flipping.
_EVIDENCE_KINDS: frozenset[str] = frozenset(
    {
        "predicate.evaluated",
        "tool.result",
        "response.received",  # only counts when a *different* provider (companion)
        "investigator.report",
    }
)


def _extract_assistant_text(event: "Event") -> str:
    """Return the text field an assistant-turn event exposes.

    We accept several payload shapes so ``scan_trace`` can be fed from
    the substrate ``response.received`` event, from provider-adapter
    stubs, or from a test fixture. Missing text returns the empty
    string, which classifies as ``"unknown"`` and cannot trigger a
    reversal on its own.
    """
    payload = event.payload or {}
    for key in ("assistant_text", "text", "content", "response_text", "body"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _is_assistant_turn(event: "Event") -> bool:
    """Return ``True`` when ``event`` is a primary-assistant turn.

    The substrate ``response.received`` kind carries an ``role`` /
    ``provider_role`` payload key naming which side spoke. When the
    payload names the primary (default), the event is a candidate for
    reversal analysis. Companion responses count as evidence (per
    ``_EVIDENCE_KINDS``) rather than as assistant turns.
    """
    if event.kind != "response.received":
        return False
    payload = event.payload or {}
    role = payload.get("role") or payload.get("provider_role") or "primary"
    return role == "primary"


def _is_investigator_chain(events_between: list["Event"]) -> bool:
    """Return ``True`` when ``events_between`` includes an Investigator report.

    Investigator-driven position changes are legitimate: they are the
    whole point of the pre-completion contract. Any reversal chain that
    includes an ``investigator.report`` event is exempted from the
    suspicious classification, even when no other evidence landed.
    """
    return any(e.kind == "investigator.report" for e in events_between)


def scan_trace(
    events: Iterable["Event"],
    window: int = 5,
) -> tuple[ReversalReport, ...]:
    """Find suspicious reversals in the assistant-turn stream.

    Iterates over ``events`` in order. For each pair of assistant turns
    where the second turn is within ``window`` turns of the first, the
    classifier compares labels; a distinct-and-non-``unknown`` pair with
    no intervening accepted evidence is reported as suspicious. The
    return is the full set of reversal reports (both suspicious and
    absorbed) so callers can render them.
    """
    events_list = list(events)
    assistant_indices: list[int] = [
        i for i, e in enumerate(events_list) if _is_assistant_turn(e)
    ]

    reports: list[ReversalReport] = []
    for i, ai in enumerate(assistant_indices):
        e1 = events_list[ai]
        label1 = _classify_position(_extract_assistant_text(e1))
        if label1 == "unknown":
            continue
        # Look at the next up-to-``window`` assistant turns.
        for aj in assistant_indices[i + 1 : i + 1 + window]:
            e2 = events_list[aj]
            label2 = _classify_position(_extract_assistant_text(e2))
            if label2 == "unknown":
                continue
            if label1 == label2:
                continue
            between = events_list[ai + 1 : aj]
            evidence_ids: list[bytes] = [
                e.id for e in between if e.kind in _EVIDENCE_KINDS
            ]
            is_suspicious = (
                len(evidence_ids) == 0 and not _is_investigator_chain(between)
            )
            reports.append(
                ReversalReport(
                    position_1_event_id=e1.id,
                    position_2_event_id=e2.id,
                    position_1_label=label1,
                    position_2_label=label2,
                    intervening_evidence_events=tuple(evidence_ids),
                    is_suspicious=is_suspicious,
                )
            )
            # Only report the closest reversal — deeper pairs would
            # re-report the same conflict from a shifted anchor.
            break
    return tuple(reports)


# ---------------------------------------------------------------------------
# force_evidence_or_restore — inject the forcing prompt
# ---------------------------------------------------------------------------


def force_evidence_or_restore(
    reversal: ReversalReport,
    loop: _RepairIntentSink,
) -> None:
    """Queue a forcing prompt on ``loop`` naming ``reversal``.

    ``loop`` is any object that satisfies the ``_RepairIntentSink``
    Protocol above — the substrate ``LoopController`` and any
    test-double with a settable ``_repair_intent`` attribute qualify.
    Setting ``_repair_intent`` prepends the string to the next
    iteration's intent so the primary sees the challenge before
    speaking again.

    The prompt names the two conflicting turns by short id and asks
    for either (a) fresh evidence justifying the change or (b) an
    explicit restoration of the earlier position. The prompt does not
    itself decide which; that is the primary's job.
    """
    prompt = (
        "[REVERSAL CHALLENGE] The trace shows two assistant turns with "
        f"opposing positions (turn {reversal.position_1_event_id[:4].hex()} "
        f"said {reversal.position_1_label!r}; turn "
        f"{reversal.position_2_event_id[:4].hex()} said "
        f"{reversal.position_2_label!r}) with no intervening evidence in the "
        "trace (no predicate evaluation, no tool result, no companion "
        "response, no Investigator report between them). Produce the "
        "evidence that justifies the change, or restore the earlier "
        "position. Do not silently continue with the reversed position."
    )
    loop._repair_intent = prompt


# ---------------------------------------------------------------------------
# taint_run — reversal taint the rootknot carries
# ---------------------------------------------------------------------------


def taint_run(
    reports: tuple[ReversalReport, ...],
    operator_accepted: bool,
) -> Literal["clean", "partial"]:
    """Return the reversal taint value that feeds the rootknot.

    Rules:
    - Zero suspicious reversals: ``"clean"``.
    - Any suspicious reversal AND ``operator_accepted=False``:
      ``"partial"``. The rootknot verifier's AL-1.3 then requires an
      out-of-band operator handshake before the artifact verifies.
    - Any suspicious reversal AND ``operator_accepted=True``:
      ``"partial"`` (the taint is still recorded — the operator is
      accepting the partial status, not erasing it).
    """
    suspicious = [r for r in reports if r.is_suspicious]
    if not suspicious:
        return "clean"
    _ = operator_accepted  # taint is recorded regardless; acceptance is at verify time
    return "partial"


# ---------------------------------------------------------------------------
# _emit — best-effort trace emit of the suspicious-reversal event
# ---------------------------------------------------------------------------


def emit_reversal_suspicious_event(report: ReversalReport) -> None:
    """Best-effort emit of a ``reversal.suspicious`` event.

    Called by the scanner site after a suspicious reversal is
    surfaced. Local import breaks the ``trace`` → ``antilazy`` cycle.
    Never fails on trace error (per the substrate never-fail-on-trace
    invariant module_03 preserved).
    """
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "reversal.suspicious",
            {
                "position_1_event_id": report.position_1_event_id.hex(),
                "position_2_event_id": report.position_2_event_id.hex(),
                "position_1_label": report.position_1_label,
                "position_2_label": report.position_2_label,
                "intervening_evidence_events": [
                    e.hex() for e in report.intervening_evidence_events
                ],
                "is_suspicious": report.is_suspicious,
            },
        )
    except Exception:  # noqa: BLE001
        pass


__all__ = [
    "PositionLabel",
    "ReversalReport",
    "emit_reversal_suspicious_event",
    "force_evidence_or_restore",
    "scan_trace",
    "taint_run",
]


# RACT 0.4.0
