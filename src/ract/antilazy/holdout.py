"""ALM Gate G1 — held-out predicate enforcement.

The substrate (``ract.core.compile.IntentCompiler``) produces a single
``AcceptanceSuite``. G1 splits that into a visible half the model sees
and a held-out half the environment keeps sealed under a symmetric key
derived from the run's ``SandboxKey``. T1 (Completion) reads both
halves; a run that passes visible predicates while failing held-out
predicates emits ``laziness.violated`` with ``kind="visible_holdout_gap"``.

See ``docs/RACT_v0.4.0_ANTILAZY_SPEC.md`` §3.1 for the design and
``docs/ADRs/ADR-0019-antilazy-holdout-and-mutation-kill.md`` for the
rejected alternatives.
"""

from __future__ import annotations

import base64
import json
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ract.core.predicate import (
    _REDACT_PREDICATE_ID,
    AcceptancePredicate,
    AcceptanceSuite,
    suite_from_canonical,
)

if TYPE_CHECKING:
    from ract.core.loop import WorkspaceSnapshot
    from ract.security.keys import SandboxKey


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


HoldoutKind = Literal["real", "trivial"]

# ALM module_04 addition — closes module_01's flagged gap
# "``holdout_kind='trivial'`` silently disables held-out enforcement."
# The composer's rolling trivial-rate (over the last N compositions,
# default N=20) is bounded from above by a ceiling (default 0.3, i.e.
# no more than 30% of intents may compose trivially). Above the
# ceiling ``enforce_trivial_rate_ceiling`` raises and
# ``compile_held_out`` refuses to return a new suite.

DEFAULT_TRIVIAL_RATE_CEILING: float = 0.3
"""No more than this fraction of the composer's last N compositions
may be ``holdout_kind='trivial'``. Above this the compile refuses."""

DEFAULT_TRIVIAL_RATE_WINDOW: int = 20
"""Sliding window size for the trivial-rate check."""


@dataclass(frozen=True)
class HoldoutCompilationRecord:
    """One entry in the composer's rolling trivial-rate history.

    A record captures the outcome of one ``compile_held_out`` call:
    the composer's identifier (``composer_name``) and the resulting
    ``holdout_kind`` ("real" or "trivial"). The compiler builds a
    tuple of these records across compositions and feeds it to
    ``enforce_trivial_rate_ceiling`` at each new call.

    Callers persist the history however they like; the check is
    memoryless (the ceiling is a function of the tuple, not of
    hidden state).
    """

    composer_name: str
    holdout_kind: HoldoutKind


class TrivialRateCeilingExceededError(RuntimeError):
    """Raised by ``enforce_trivial_rate_ceiling`` when the composer's
    rolling trivial rate is above the ceiling.

    The compiler catches this and refuses to compile a new held-out
    suite until the operator investigates the composer that keeps
    producing trivial suites (module_01 flagged gap: a model that
    biases the composer into always-trivial output silently bypasses
    G1; the ceiling makes the pattern loud instead of silent).
    """


def enforce_trivial_rate_ceiling(
    composer_history: tuple[HoldoutCompilationRecord, ...],
    ceiling: float = DEFAULT_TRIVIAL_RATE_CEILING,
    *,
    window: int = DEFAULT_TRIVIAL_RATE_WINDOW,
) -> None:
    """Raise ``TrivialRateCeilingExceededError`` when the composer's
    rolling trivial rate over the last ``window`` records exceeds
    ``ceiling``.

    A history shorter than ``window`` uses the full history it has.
    An empty history is a pass — a fresh pipeline hasn't yet earned
    the right to be suspicious.

    Emits ``laziness.violated`` with ``kind="trivial_rate_ceiling_
    exceeded"`` on refusal (best-effort; never fails the check on a
    trace-writer error).
    """
    if not composer_history:
        return
    recent = composer_history[-window:] if window > 0 else composer_history
    trivial_count = sum(
        1 for r in recent if r.holdout_kind == "trivial"
    )
    total = len(recent)
    if total == 0:
        return
    rate = trivial_count / total
    if rate <= ceiling:
        return
    # Refuse — emit and raise.
    composer_names = sorted({r.composer_name for r in recent})
    try:  # local import breaks the trace→antilazy cycle
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "laziness.violated",
            {
                "kind": "trivial_rate_ceiling_exceeded",
                "trivial_rate": round(rate, 4),
                "ceiling": ceiling,
                "window": total,
                "trivial_count": trivial_count,
                "composer_names": composer_names,
            },
        )
    except Exception:  # noqa: BLE001 — never fail on trace error
        pass
    raise TrivialRateCeilingExceededError(
        f"composer trivial rate {rate:.3f} exceeds ceiling {ceiling:.3f} "
        f"over last {total} composition(s); refusing to compile a new "
        f"held-out suite. Composer(s) implicated: {composer_names!r}. "
        "Investigate the composer that keeps producing trivial suites "
        "(module_01 flagged gap closed by module_04)."
    )
"""Whether the held-out suite carries composed predicates.

``"real"``: the companion produced at least one non-trivial held-out
predicate (distinguishes the current workspace from a byte-shuffled
perturbation of the touched surface).

``"trivial"``: the companion could not compose non-trivial predicates
for this intent (lateral chain branch E). T1 treats a trivial
held-out as auto-pass; the escape hatch is logged so a rate spike is
visible in the trace.
"""


# HKDF context strings — stable across releases so an archived run's
# seal can still be opened. Bumping either string is a breaking change
# that would leave old seals un-openable.
_AEAD_CONTEXT: bytes = b"ract/antilazy/holdout-seal/v1"
_AEAD_INFO: bytes = b"AES-256-GCM"
_AEAD_KEY_LEN: int = 32
_AEAD_NONCE_LEN: int = 12


# ---------------------------------------------------------------------------
# HoldoutComposer protocol (companion-shaped)
# ---------------------------------------------------------------------------


@runtime_checkable
class HoldoutComposer(Protocol):
    """The companion-shaped composer that produces held-out predicates.

    The substrate ``Provider`` protocol (``ract.providers.provider``)
    speaks the wire protocol; ``HoldoutComposer`` is the higher-level
    verb the ALM layer needs. Adapters may implement both — a
    production companion wraps a ``Provider`` and translates
    ``compose(visible, ws) -> AcceptanceSuite`` into a specific
    ``send_planned_step_request`` call whose response is parsed as an
    ``AcceptanceSuite``. Tests inject a direct implementation.
    """

    def compose(
        self, visible: AcceptanceSuite, ws: "WorkspaceSnapshot"
    ) -> AcceptanceSuite:
        """Return a held-out ``AcceptanceSuite`` composed from ``visible``.

        The composer MAY return an empty-``predicates`` suite when no
        composition is possible for this intent; ``compose_held_out``
        marks such returns ``holdout_kind="trivial"``.
        """
        ...  # pragma: no cover — protocol


# ---------------------------------------------------------------------------
# DualAcceptanceSuite
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DualAcceptanceSuite:
    """Visible + held-out acceptance suites bound by the sandbox seal.

    - ``visible``: the ``AcceptanceSuite`` the model-facing tools can
      read. Same shape as the substrate return type; substrate callers
      that reach through ``.visible`` continue to work.
    - ``held_out``: the composed suite the environment enforces. Never
      exposed to model-facing capabilities.
    - ``held_out_digest``: the SHA-256 digest of the held-out suite's
      canonical form. Committed publicly for later audit — the operator
      can prove which suite was enforced without seeing the predicates.
    - ``held_out_seal``: the AES-256-GCM ciphertext of the held-out
      suite's canonical JSON, produced under a key derived from the
      run's ``SandboxKey``. The first ``_AEAD_NONCE_LEN`` bytes are
      the nonce.
    - ``holdout_kind``: ``"real"`` when held-out carries predicates
      that distinguish the workspace from a byte-shuffled perturbation
      of the touched surface; ``"trivial"`` when the composer could
      not produce such predicates and the held-out check auto-passes.
    """

    visible: AcceptanceSuite
    held_out: AcceptanceSuite
    held_out_digest: str
    held_out_seal: bytes
    holdout_kind: HoldoutKind = "real"

    def __post_init__(self) -> None:
        if self.visible.intent_id != self.held_out.intent_id:
            raise ValueError(
                "visible.intent_id and held_out.intent_id must match; "
                f"got {self.visible.intent_id.hex()} vs "
                f"{self.held_out.intent_id.hex()}"
            )
        if self.holdout_kind not in ("real", "trivial"):
            raise ValueError(f"unknown holdout_kind: {self.holdout_kind!r}")
        if self.holdout_kind == "trivial" and self.held_out.predicates:
            raise ValueError(
                "holdout_kind='trivial' requires held_out.predicates=()"
            )

    def required(self) -> tuple[AcceptancePredicate, ...]:
        """Return required predicates from visible + held_out concatenated.

        Substrate ``check_t1`` iterates ``suite.required()``; the dual
        suite exposes both halves so the substrate path terminates only
        when both halves pass. When ``holdout_kind="trivial"`` the
        held-out contributes no required predicates (empty tuple), so
        T1 falls back to visible-only.
        """
        return self.visible.required() + self.held_out.required()

    @property
    def intent_id(self) -> bytes:
        """Delegate to ``visible.intent_id`` so DualAcceptanceSuite is
        transparent to substrate helpers that read ``.intent_id``."""
        return self.visible.intent_id

    @property
    def predicates(self) -> tuple[AcceptancePredicate, ...]:
        """Concatenated predicates (visible + held_out) — substrate
        compatibility for LoopState constructors that touch ``.predicates``.
        """
        return self.visible.predicates + self.held_out.predicates

    def to_canonical(self) -> dict[str, Any]:
        """Return the on-disk canonical form for ``suite.json``.

        Only ``held_out_digest`` is committed in the clear alongside
        ``held_out_seal``; the plaintext of ``held_out`` never lands on
        disk in an unencrypted field.
        """
        return {
            "visible": self.visible.to_canonical(),
            "held_out_digest": self.held_out_digest,
            "held_out_seal": base64.b64encode(self.held_out_seal).decode("ascii"),
            "holdout_kind": self.holdout_kind,
        }


# ---------------------------------------------------------------------------
# Compose held-out via companion, with non-triviality check
# ---------------------------------------------------------------------------


def _perturb_snapshot(
    ws: "WorkspaceSnapshot", touched: tuple[str, ...], *, seed: int = 0xA1
) -> "WorkspaceSnapshot":
    """Return a copy of ``ws`` with ``touched`` file contents byte-shuffled.

    The perturbation is deterministic (fixed seed) so the non-triviality
    check is reproducible run-to-run. Files not in ``touched`` are
    copied by reference. Metadata is copied — a byte-shuffle inside a
    file does not change pytest exit records the compiler stashed in
    ``ws.metadata``, which is exactly what we want when the held-out
    predicates read those channels: only artifact / assertion / type
    invocations that literally inspect file content distinguish the
    two snapshots.
    """
    # Local import breaks the antilazy -> core.loop cycle at module load.
    from ract.core.loop import WorkspaceSnapshot

    rng = random.Random(seed)
    files = dict(ws.files)
    touched_set = set(touched)
    for path in list(files.keys()):
        if path not in touched_set:
            continue
        raw = files[path].encode("utf-8", errors="replace")
        if not raw:
            continue
        buf = bytearray(raw)
        rng.shuffle(buf)
        files[path] = buf.decode("utf-8", errors="replace")
    return WorkspaceSnapshot(
        files=files,
        timestamp=ws.timestamp,
        metadata=dict(ws.metadata),
    )


def _is_non_trivial(
    held_out: AcceptanceSuite,
    ws: "WorkspaceSnapshot",
    touched: tuple[str, ...],
) -> bool:
    """Return True when at least one held-out predicate distinguishes
    ``ws`` from a byte-shuffled perturbation of ``touched``.

    A held-out suite that evaluates identically on the original and
    perturbed snapshots is theatre — the visible suite already covers
    what it claims to cover. Reject such suites by returning False.
    """
    if not held_out.predicates:
        return False
    perturbed = _perturb_snapshot(ws, touched)
    # ALM module_01 second-pass fix (finding 1): redact predicate ids
    # in the trace during the non-triviality check too. Compile-time
    # evaluations of the composed held-out set would otherwise leak
    # the ids before the model even sees the visible suite.
    token = _REDACT_PREDICATE_ID.set(True)
    try:
        for predicate in held_out.predicates:
            original = predicate.evaluate(ws)
            shuffled = predicate.evaluate(perturbed)
            if original.ok != shuffled.ok:
                return True
    finally:
        _REDACT_PREDICATE_ID.reset(token)
    return False


def compose_held_out(
    visible: AcceptanceSuite,
    ws: "WorkspaceSnapshot",
    composer: HoldoutComposer,
    *,
    touched: tuple[str, ...] = (),
    composer_history: tuple[HoldoutCompilationRecord, ...] = (),
    trivial_rate_ceiling: float = DEFAULT_TRIVIAL_RATE_CEILING,
    trivial_rate_window: int = DEFAULT_TRIVIAL_RATE_WINDOW,
) -> tuple[AcceptanceSuite, HoldoutKind]:
    """Ask ``composer`` to produce held-out predicates; verify non-trivial.

    Returns ``(held_out_suite, holdout_kind)``. The ``held_out_suite``
    always carries the intent_id of ``visible``; on ``kind="trivial"``
    it carries an empty ``predicates`` tuple and T1 treats the
    held-out check as auto-pass.

    Lateral chain branch E: some intents ("format the codebase with
    black") admit no composition. The composer signals that either by
    returning an empty-``predicates`` suite or by returning a suite
    whose predicates all evaluate identically on ``ws`` and on a
    byte-shuffled perturbation of ``touched``.

    ALM module_04 addition — trivial-rate ceiling (module_01 gap).
    When ``composer_history`` is supplied, the ceiling is enforced
    BEFORE the composer is called; if the composer has been producing
    trivial suites at a rate above the ceiling, ``compose_held_out``
    raises ``TrivialRateCeilingExceededError`` rather than adding
    another silent auto-pass to the pile.
    """
    enforce_trivial_rate_ceiling(
        composer_history,
        trivial_rate_ceiling,
        window=trivial_rate_window,
    )
    proposed = composer.compose(visible, ws)
    if proposed.intent_id != visible.intent_id:
        proposed = AcceptanceSuite(
            intent_id=visible.intent_id,
            predicates=proposed.predicates,
            coverage_gate=proposed.coverage_gate,
            compiled_from=proposed.compiled_from,
            compiler_version=proposed.compiler_version,
        )
    if not proposed.predicates:
        empty = AcceptanceSuite(
            intent_id=visible.intent_id,
            predicates=(),
            coverage_gate=visible.coverage_gate,
            compiled_from=visible.compiled_from,
            compiler_version=visible.compiler_version,
        )
        return empty, "trivial"
    if not _is_non_trivial(proposed, ws, touched):
        empty = AcceptanceSuite(
            intent_id=visible.intent_id,
            predicates=(),
            coverage_gate=visible.coverage_gate,
            compiled_from=visible.compiled_from,
            compiler_version=visible.compiler_version,
        )
        return empty, "trivial"
    return proposed, "real"


# ---------------------------------------------------------------------------
# Seal / unseal
# ---------------------------------------------------------------------------


def _derive_aead_key(sandbox_key: "SandboxKey") -> bytes:
    """Derive a 32-byte AES-GCM key from the sandbox signing key.

    HKDF-SHA256 over ``sandbox_key.sign(_AEAD_CONTEXT)`` produces a
    stable per-run symmetric key without exposing the Ed25519 private
    bytes. The context string is a load-bearing constant; bumping it
    would leave old seals un-openable.
    """
    ikm = sandbox_key.sign(_AEAD_CONTEXT)
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=_AEAD_KEY_LEN,
        salt=sandbox_key.public,
        info=_AEAD_INFO,
    )
    return hkdf.derive(ikm)


def seal_held_out(suite: AcceptanceSuite, sandbox_key: "SandboxKey") -> bytes:
    """Return the AES-256-GCM ciphertext of ``suite`` under ``sandbox_key``.

    Wire shape: ``nonce (12 bytes) || AES-GCM(ciphertext + tag)``. The
    canonical JSON of ``suite`` is the plaintext. The sandbox capability
    manifest refuses to expose the resulting bytes to any model-facing
    tool.
    """
    key = _derive_aead_key(sandbox_key)
    nonce = os.urandom(_AEAD_NONCE_LEN)
    plaintext = suite.to_json().encode("utf-8")
    aead = AESGCM(key)
    ciphertext = aead.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def unseal_held_out(seal: bytes, sandbox_key: "SandboxKey") -> AcceptanceSuite:
    """Return the ``AcceptanceSuite`` recovered from ``seal``.

    Raises ``ValueError`` when the seal is malformed or the AEAD
    integrity tag fails (wrong key, corrupted bytes).
    """
    if len(seal) < _AEAD_NONCE_LEN + 16:
        raise ValueError("seal too short to contain nonce + AEAD tag")
    key = _derive_aead_key(sandbox_key)
    nonce = seal[:_AEAD_NONCE_LEN]
    ciphertext = seal[_AEAD_NONCE_LEN:]
    aead = AESGCM(key)
    try:
        plaintext = aead.decrypt(nonce, ciphertext, None)
    except Exception as exc:  # noqa: BLE001 — AEAD library exceptions vary
        raise ValueError(f"AEAD unseal failed: {exc}") from exc
    return suite_from_canonical(json.loads(plaintext.decode("utf-8")))


# ---------------------------------------------------------------------------
# T1 dual-suite evaluator (visible + held_out)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisibleHoldoutOutcome:
    """Outcome of evaluating a ``DualAcceptanceSuite`` against a snapshot.

    - ``visible_ok``: all required visible predicates evaluate ``ok``.
    - ``held_out_ok``: all required held-out predicates evaluate ``ok``
      (auto-True for ``holdout_kind="trivial"``).
    - ``gap``: True iff ``visible_ok and not held_out_ok`` — the
      laziness signature the ALM was written to catch.
    - ``failing_visible``: ids of required visible predicates that
      evaluated ``not ok``.
    - ``failing_held_out``: ids of required held-out predicates that
      evaluated ``not ok``.
    """

    visible_ok: bool
    held_out_ok: bool
    gap: bool
    failing_visible: tuple[str, ...] = field(default_factory=tuple)
    failing_held_out: tuple[str, ...] = field(default_factory=tuple)


def check_visible_and_held_out(
    dual: DualAcceptanceSuite, snapshot: "WorkspaceSnapshot"
) -> VisibleHoldoutOutcome:
    """Evaluate both halves; emit ``laziness.violated`` when gap fires.

    The emit is best-effort (never raises); the outcome is always
    returned. Substrate T1 (``ract.core.loop.check_t1``) reads
    ``DualAcceptanceSuite.required()`` which concatenates both halves,
    so the loop-level completion check is unchanged. This function is
    what the pre-commit gate and the report layer call when they need
    the ``gap`` signal specifically.
    """
    failing_visible: list[str] = []
    for predicate in dual.visible.required():
        if not predicate.evaluate(snapshot).ok:
            failing_visible.append(predicate.id.hex())
    failing_held_out: list[str] = []
    if dual.holdout_kind == "real":
        # ALM module_01 second-pass fix (finding 1): set the substrate
        # predicate-id redaction flag while iterating held-out
        # predicates so their ids do not appear in the
        # ``predicate.evaluated`` events the trace surface carries.
        # The raw id stays inside this frame; only the digest reaches
        # the event log.
        token = _REDACT_PREDICATE_ID.set(True)
        try:
            for predicate in dual.held_out.required():
                if not predicate.evaluate(snapshot).ok:
                    failing_held_out.append(predicate.id.hex())
        finally:
            _REDACT_PREDICATE_ID.reset(token)
    visible_ok = not failing_visible
    held_out_ok = not failing_held_out
    gap = visible_ok and not held_out_ok
    if gap:
        try:  # local import breaks the trace→antilazy cycle
            from ract.trace.sink import emit as _emit_event

            _emit_event(
                "laziness.violated",
                {
                    "kind": "visible_holdout_gap",
                    "intent_id": dual.intent_id.hex(),
                    "visible_digest": dual.visible.digest(),
                    "held_out_digest": dual.held_out_digest,
                    # Lateral chain branch A: model-facing readers see
                    # only counts of failing held-out predicates plus
                    # the committed digest. The raw ids stay off the
                    # public trace surface.
                    "failing_visible_count": len(failing_visible),
                    "failing_held_out_count": len(failing_held_out),
                    "holdout_kind": dual.holdout_kind,
                },
            )
        except Exception:  # noqa: BLE001 — never fail check on trace error
            pass
    return VisibleHoldoutOutcome(
        visible_ok=visible_ok,
        held_out_ok=held_out_ok,
        gap=gap,
        failing_visible=tuple(failing_visible),
        failing_held_out=tuple(failing_held_out),
    )


# ---------------------------------------------------------------------------
# On-disk snapshot writer for evals/runs/<run_id>/suite.json
# ---------------------------------------------------------------------------


def write_dual_suite_snapshot(run_dir: Path, dual: DualAcceptanceSuite) -> Path:
    """Persist the dual suite to ``<run_dir>/suite.json`` and return the path.

    The file carries the visible suite in the clear (substrate parity)
    plus the held-out digest and base64-encoded seal. The plaintext of
    the held-out predicates never lands on disk in this file.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "suite.json"
    payload = dual.to_canonical()
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


# RACT 0.4.0
