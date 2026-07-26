"""Response validator — every provider response passes through here.

SUBSTRATE §5.2 + §5.4. The validator is the choke point between the
provider layer and the executor: it takes raw responses (either a JSON
string or a pre-parsed dict) and produces a validated
``PlannedStep`` or a ``ValidationOutcome`` that names the failure.

Two-strike halt (SUBSTRATE §5.4 → T7). The validator tracks
per-``step_id`` consecutive failures. The first failure of a given step
returns ``ValidationOutcome`` with ``corrective_prompt`` set — the loop
resubmits with that prompt attached. The second consecutive failure of
the *same* step id flips ``should_halt`` and names
``TerminationCause.PROVIDER_TIMEOUT`` (T7). The v0.4 loop already
carries that termination cause (``ract.core.loop.TerminationCause``);
this module hands it a specific reason.

The corrective prompt is deterministic — it quotes the offending field
and the schema's accepted shape — so the provider trace is auditable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ract.core.actions import PlannedStep


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationOutcome:
    """Result of validating one provider response.

    Exactly one of ``planned_step`` / ``error`` is set. When ``error`` is
    set, ``corrective_prompt`` gives the caller a ready-to-attach reason
    to send to the model on the next attempt. When ``should_halt`` is
    ``True``, the loop must not resubmit; T7 has fired.
    """

    planned_step: PlannedStep | None = None
    error: str | None = None
    corrective_prompt: str | None = None
    should_halt: bool = False
    step_id: str | None = None


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


@dataclass
class ResponseValidator:
    """Parse raw provider responses into ``PlannedStep`` values.

    ``_failures`` counts consecutive failures per step id so a repeated
    failure of the same step is the T7 halt trigger; a fresh step id
    resets the count for that id.
    """

    _failures: dict[str, int] = field(default_factory=dict)

    def parse(self, raw_response: str | dict[str, Any]) -> ValidationOutcome:
        """Validate a raw response, tracking consecutive failures per step.

        ``raw_response`` may be a JSON string, a pre-parsed dict, or an
        Anthropic-style tool-use response dict containing a ``kind``
        selection at the top level. The validator normalises to a dict
        before dispatching to Pydantic.
        """
        payload, decode_error = self._to_dict(raw_response)
        step_id = self._extract_step_id(payload) if payload else None

        if decode_error is not None:
            corrective = (
                "Your response was not valid JSON. Reply with a single JSON "
                "object matching the PlannedStep schema. Decode error: "
                f"{decode_error}"
            )
            return self._record_failure(
                step_id, decode_error, corrective, source_raw=raw_response
            )

        assert payload is not None  # narrowed by the branch above
        try:
            step = PlannedStep.model_validate(payload)
        except ValidationError as exc:
            message = self._pydantic_error_message(exc)
            corrective = self._build_corrective_prompt(payload, exc)
            return self._record_failure(step_id, message, corrective)

        # Success clears the per-step failure count.
        if step.step_id in self._failures:
            del self._failures[step.step_id]
        return ValidationOutcome(planned_step=step, step_id=step.step_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _to_dict(
        self, raw: str | dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Normalise the input into a dict, or return a decode error string."""
        if isinstance(raw, dict):
            return raw, None
        if isinstance(raw, (bytes, bytearray)):
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                return None, f"utf-8 decode: {exc}"
            return self._to_dict(text)
        if isinstance(raw, str):
            try:
                loaded = json.loads(raw)
            except json.JSONDecodeError as exc:
                return None, str(exc)
            if not isinstance(loaded, dict):
                return None, (
                    f"response must decode to a JSON object; got {type(loaded).__name__}"
                )
            return loaded, None
        return None, f"unsupported response type: {type(raw).__name__}"

    def _extract_step_id(self, payload: dict[str, Any]) -> str | None:
        candidate = payload.get("step_id")
        if isinstance(candidate, str):
            return candidate
        return None

    def _record_failure(
        self,
        step_id: str | None,
        error: str,
        corrective_prompt: str,
        source_raw: str | dict[str, Any] | None = None,
    ) -> ValidationOutcome:
        """Bump the per-step failure count and decide whether T7 fires."""
        _ = source_raw  # reserved for future audit-log line
        # A response with no parseable step id is bucketed under the
        # sentinel ``"<unknown>"`` so a stream of unparsable garbage still
        # trips T7 rather than piling up unbounded.
        bucket = step_id or "<unknown>"
        self._failures[bucket] = self._failures.get(bucket, 0) + 1
        halt = self._failures[bucket] >= 2
        return ValidationOutcome(
            error=error,
            corrective_prompt=corrective_prompt,
            should_halt=halt,
            step_id=step_id,
        )

    def _pydantic_error_message(self, exc: ValidationError) -> str:
        parts: list[str] = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()))
            msg = err.get("msg", "invalid")
            parts.append(f"{loc}: {msg}" if loc else msg)
        return "; ".join(parts) if parts else str(exc)

    def _build_corrective_prompt(
        self, payload: dict[str, Any], exc: ValidationError
    ) -> str:
        """Compose a corrective prompt naming the offending field.

        The prompt is deterministic and short. It quotes the first
        offending error location and reminds the model of the closed
        union's ``kind`` set — the same set the schema converter
        enumerates for it.
        """
        errors = exc.errors()
        first = errors[0] if errors else {"loc": (), "msg": "invalid"}
        loc_parts = ".".join(str(p) for p in first.get("loc", ()))
        msg = first.get("msg", "invalid")
        kind = None
        action = payload.get("action")
        if isinstance(action, dict):
            kind = action.get("kind")
        legal_kinds = (
            "write_file, run_tests, read_file, search_workspace, "
            "propose_predicate, delete_file, request_handshake, emit_event"
        )
        lines = [
            "Your last response failed schema validation.",
            f"Offending field: {loc_parts or '<top-level>'}",
            f"Reason: {msg}",
        ]
        if kind is not None:
            lines.append(f"You proposed action.kind={kind!r}.")
        lines.append(f"Legal action.kind values: {legal_kinds}.")
        lines.append(
            "Reply again with a single JSON object matching the PlannedStep "
            "schema. Do not add fields; do not remove required fields."
        )
        return "\n".join(lines)


__all__ = ["ResponseValidator", "ValidationOutcome"]


# RACT 0.4.0
