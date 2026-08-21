"""Operator-signed intent recompile for v0.5.1 module_04.

Legitimate intent evolution (operator refines the spec mid-run) is
distinguished from attacker injection by an operator-signed record
appended to ``<run_dir>/suite_chain.jsonl``. The loop controller
compares the current intent against the LATEST chain entry -- a
suite version added by this module lets the run continue; anything
else trips T8 PROMPT_DRIFT.

Operator authorisation:

- Marker file: ``.ract/operator.key`` under the workspace root (or
  the caller-provided ``ract_dir``). Any 32-or-more-byte file
  qualifies; the bytes are used as HMAC-like signing input to the
  recompile Rootknot. Missing or short file -> refusal with a
  clear error.
- Env var: ``RACT_OPERATOR_KEY`` -- 64-hex-char string of at least
  32 bytes when decoded. Used when the marker file is absent (CI
  environments). Present-but-invalid -> refusal.

Priority: marker file first, then env var. At least one must be
present + valid; otherwise :class:`OperatorKeyMissingError` is
raised BEFORE any state is written.

Reference:
- ``docs/ADRs/ADR-0040-t8-prompt-drift-termination-cause.md``.
- ``src/ract/core/suite_chain.py`` (chain append).
- ``src/ract/core/compile.py`` (``IntentCompiler``).
- ``src/ract/cli.py`` (``ract intent recompile`` verb).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass
from pathlib import Path

_LOG = logging.getLogger("ract.core.intent_recompile")

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)

from typing import TYPE_CHECKING

from ract.core.predicate import AcceptanceSuite
from ract.core.suite_chain import SuiteChain, SuiteChainEntry
from ract.core.workspace_digest import compute_prompt_digest

if TYPE_CHECKING:
    from ract.core.loop import WorkspaceSnapshot

# ``O_BINARY`` on Windows; no-op flag on POSIX. Same lesson as the
# workspace-chain + WAL modules: binary-mode fds under the lock.
_BINARY_FLAG = getattr(os, "O_BINARY", 0)


OPERATOR_KEY_FILENAME = "operator.key"
OPERATOR_KEY_ENV = "RACT_OPERATOR_KEY"
_MIN_KEY_BYTES = 32


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OperatorKeyMissingError(RuntimeError):
    """Raised when no valid operator key is available.

    Neither the marker file ``.ract/operator.key`` nor the env var
    ``RACT_OPERATOR_KEY`` supplied a >= 32-byte key. The recompile
    action is refused BEFORE any state is written -- an attacker
    without the operator key cannot append a suite-chain entry, so
    T8 PROMPT_DRIFT fires on their intent change.
    """


class IntentRecompileError(RuntimeError):
    """Raised when a recompile request is otherwise invalid.

    Wraps compilation errors, missing run directories, and empty
    intent-text arguments. Preserves the underlying exception via
    ``__cause__``.
    """


# ---------------------------------------------------------------------------
# Operator key loading
# ---------------------------------------------------------------------------


def _load_operator_key(ract_dir: Path) -> bytes:
    """Return the operator key bytes.

    Prefers the marker file ``<ract_dir>/operator.key``; falls back
    to the ``RACT_OPERATOR_KEY`` env var. Raises
    :class:`OperatorKeyMissingError` when neither yields >= 32 bytes.

    v0.5.1 module_04 SP Q4a amendment (OpenRouter reviewer DEFECT verdict): the
    ract_dir path is resolved through ``Path.resolve(strict=False)``
    so a caller-supplied relative path or a symlink race cannot
    redirect the loader to a decoy operator.key. The resolved path is
    what actually gets joined with ``operator.key`` -- any
    symlink-following happens at OS filesystem level and is bounded
    by the resolved parent directory.
    """
    ract_dir = ract_dir.resolve(strict=False)
    key_path = ract_dir / OPERATOR_KEY_FILENAME
    if key_path.exists():
        try:
            key_bytes = key_path.read_bytes()
        except OSError as exc:
            raise OperatorKeyMissingError(
                f"operator.key at {key_path} exists but cannot be read: {exc}"
            ) from exc
        # Strip trailing whitespace so a text-file marker with a
        # newline still qualifies.
        key_bytes = key_bytes.strip()
        if len(key_bytes) >= _MIN_KEY_BYTES:
            return key_bytes
        raise OperatorKeyMissingError(
            f"operator.key at {key_path} is too short "
            f"(got {len(key_bytes)} bytes, need >= {_MIN_KEY_BYTES}). "
            f"Generate a fresh key with, e.g., "
            f"'python -c \"import secrets; print(secrets.token_hex(32))\" "
            f"> {key_path}'."
        )
    env_val = os.environ.get(OPERATOR_KEY_ENV, "").strip()
    if env_val:
        # Accept either raw bytes (unlikely from an env var) or hex.
        try:
            decoded = bytes.fromhex(env_val)
        except ValueError:
            decoded = env_val.encode("utf-8")
        if len(decoded) >= _MIN_KEY_BYTES:
            return decoded
        raise OperatorKeyMissingError(
            f"{OPERATOR_KEY_ENV} is set but decodes to only "
            f"{len(decoded)} bytes (need >= {_MIN_KEY_BYTES}). Set a "
            "64-hex-character value (32 bytes)."
        )
    raise OperatorKeyMissingError(
        f"no operator key found. Provide one of:\n"
        f"  - marker file at {key_path} (>= {_MIN_KEY_BYTES} bytes), or\n"
        f"  - env var {OPERATOR_KEY_ENV}=<64 hex chars>."
    )


# ---------------------------------------------------------------------------
# Recompile action
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecompileResult:
    """Return value of :func:`recompile_intent`."""

    new_suite: AcceptanceSuite
    entry: SuiteChainEntry
    suite_chain_path: Path


# TODO(D9, v0.5.2): produce a real v4 Rootknot for the recompile
# action so ``SuiteChainEntry.rootknot_signature`` matches the
# suite_chain.py:19-21 docstring ("hex generator signature of the
# v4 Rootknot recording the recompile action"). Today the field
# carries HMAC-SHA256 hex; either plumb session_key + sandbox_signer
# + alm_signer through the CLI verb OR align the docstring to the
# HMAC-only reality.
def _sign_recompile(
    operator_key: bytes, suite_digest: str, prompt_digest: bytes, run_id: str
) -> bytes:
    """Return an HMAC-SHA256 signature binding the recompile action.

    The full v4 Rootknot signing surface is available but requires a
    session key + sandbox signer + ALM signer whose lifecycle is owned
    by the loop controller (not by the CLI verb). For the suite-chain
    audit record we compute a compact HMAC over the load-bearing bytes
    (``suite_digest || prompt_digest || run_id``) using the operator
    key as the HMAC secret. The intent is to prove operator possession
    of the key at recompile time; RK-3 verify does not depend on this
    signature (it verifies the sandbox key), so no signing-oracle
    concern is introduced.
    """
    mac = hmac.new(operator_key, digestmod=hashlib.sha256)
    mac.update(suite_digest.encode("utf-8"))
    mac.update(b"\x00")
    mac.update(prompt_digest)
    mac.update(b"\x00")
    mac.update(run_id.encode("utf-8"))
    return mac.digest()


def _scan_workspace_snapshot(project_dir: Path) -> "WorkspaceSnapshot":
    """Return a :class:`WorkspaceSnapshot` covering ``project_dir``.

    v0.5.1 wiring module_02 (Lens D D4): the previous recompile
    passed an EMPTY ``WorkspaceSnapshot`` to
    :meth:`IntentCompiler.compile`, so ``_discover_test_files`` found
    zero tests and the fresh suite carried zero required predicates.
    ``build_loop_state`` then rejected the recompiled run (T1's
    "suite has zero required predicates" post-init check) and the
    next iteration's ``check_t1`` gate became a silent pass -- an
    operator refine flow that legitimately unlocks T8 also silently
    disabled T1.

    Scan discipline (deterministic, bounded):

    - Sources: ``**/*.py`` under ``project_dir``, plus every file
      under a top-level ``tests/`` tree if one exists.
    - Skip: hidden dirs (``.git``, ``.ract``, ``.rack``, ``.venv``,
      ``__pycache__``, ``.mypy_cache``, ``.pytest_cache``,
      ``node_modules``).
    - Skip: files above 512 KB (source-only floor -- avoids pulling
      built artifacts, packed archives, or generated JSON blobs
      into the digest input; matches ``loop_controller._take_snapshot``
      selection heuristics).
    - Content: read as UTF-8 with ``errors="replace"`` so a binary
      hit does not raise; the snapshot is used for predicate
      discovery + workspace_digest, not for exact-byte replay.
    """
    from ract.core.loop import WorkspaceSnapshot

    files: dict[str, str] = {}
    skip_dirs = {
        ".git",
        ".ract",
        ".rack",
        ".venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        "node_modules",
        "_BUILD",
    }
    max_bytes = 512 * 1024
    for candidate in project_dir.rglob("*"):
        try:
            if not candidate.is_file():
                continue
        except OSError:
            continue
        rel_parts = candidate.relative_to(project_dir).parts
        if any(part in skip_dirs for part in rel_parts):
            continue
        # Focus on source + tests -- the two selectors the compiler
        # actually walks. Broader coverage is v0.6 territory.
        if candidate.suffix != ".py" and "tests" not in rel_parts:
            continue
        try:
            if candidate.stat().st_size > max_bytes:
                continue
            files[str(candidate.relative_to(project_dir)).replace("\\", "/")] = (
                candidate.read_text(encoding="utf-8", errors="replace")
            )
        except OSError:
            continue
    return WorkspaceSnapshot(files=files, timestamp=0.0)


def _resolve_project_dir(run_dir: Path, ract_dir: Path | None) -> Path | None:
    """Return the workspace root, or ``None`` when it cannot be located.

    Walks up from ``run_dir`` looking for the ``.ract`` sibling that
    marks the workspace root; falls back to the parent of
    ``ract_dir`` when supplied. ``None`` means "the recompile is
    running outside a discoverable workspace" -- the caller preserves
    prev_suite predicates in that case.
    """
    if ract_dir is not None:
        parent = ract_dir.resolve(strict=False).parent
        if parent.exists() and parent.is_dir():
            return parent
    candidate = run_dir
    for _ in range(6):
        if (candidate / ".ract").exists():
            return candidate
        if candidate.parent == candidate:
            break
        candidate = candidate.parent
    return None


def recompile_intent(
    *,
    run_dir: Path,
    intent_text: str,
    ract_dir: Path | None = None,
    workspace: "WorkspaceSnapshot | None" = None,
) -> RecompileResult:
    """Recompile a run's intent under an operator-signed suite-chain entry.

    Steps:

    1. Load and validate the operator key (raises
       :class:`OperatorKeyMissingError` on absent / invalid).
    2. Compile a new :class:`AcceptanceSuite` from ``intent_text``.
       :func:`ract.core.compile.IntentCompiler.compile` populates
       ``prompt_digest``.
    3. Compute the HMAC signature binding the action to the operator
       key.
    4. Append a ``suite_chain.jsonl`` entry with ``origin =
       "operator_recompile"``.
    5. Overwrite ``<run_dir>/suite.json`` with the new suite's canonical
       serialisation so a fresh load picks up the latest version. The
       chain retains the full history; the pointer file mirrors the
       chain head for convenience.

    The run's ``run_id`` is preserved -- a recompile is a mutation
    of the intent, not the creation of a new run.

    v0.5.1 wiring module_02 (Lens D D4): ``workspace`` is an optional
    :class:`WorkspaceSnapshot`. When omitted, the recompiler scans the
    workspace root (the parent of ``.ract``) for source + tests so
    :meth:`IntentCompiler.compile` sees a NON-EMPTY snapshot and the
    fresh suite carries real predicates. The earlier behaviour
    (empty-snapshot compile) silently stripped every required
    predicate and turned the next iteration's ``check_t1`` into a
    silent pass. When the workspace root cannot be located, the
    recompile preserves ``prev_suite.predicates`` verbatim rather
    than emitting a zero-predicate suite.
    """
    if not intent_text.strip():
        raise IntentRecompileError("intent_text must be non-empty")

    run_dir = Path(run_dir)
    if not run_dir.exists():
        raise IntentRecompileError(f"run directory {run_dir} does not exist")

    if ract_dir is None:
        # Walk up from run_dir until we find a .ract directory; default
        # to the run_dir's ract_dir sibling if none found.
        candidate = run_dir
        ract_dir_found: Path | None = None
        for _ in range(6):  # bounded parent walk
            candidate_ract = candidate / ".ract"
            if candidate_ract.exists() and candidate_ract.is_dir():
                ract_dir_found = candidate_ract
                break
            if candidate.parent == candidate:
                break
            candidate = candidate.parent
        ract_dir = ract_dir_found or (run_dir.parent.parent / ".ract")

    operator_key = _load_operator_key(ract_dir)

    # v0.5.1 module_04 SP Q5a amendment (OpenRouter reviewer DEFECT verdict): hold
    # a recompile lock for the ENTIRE read-compile-append-overwrite
    # sequence so two concurrent operator recompiles cannot interleave
    # (the second overwriting suite.json wins on-disk while its chain
    # entry references the first's base suite, leaving the pointer file
    # inconsistent with the chain). We use a dedicated ``.recompile_lock``
    # file in run_dir with the same cross-platform lock idiom the chain
    # itself uses, so acquiring it does not deadlock with the chain's
    # per-append lock.
    from ract.core.suite_chain import _lock_exclusive as _sc_lock
    from ract.core.suite_chain import _unlock as _sc_unlock

    lock_path = run_dir / ".recompile_lock"
    lock_path.touch(exist_ok=True)
    lock_flags = os.O_RDWR | _BINARY_FLAG
    lock_fd = os.open(lock_path, lock_flags)
    # v0.5.1 wiring module_02 (Lens D D4): materialise the workspace
    # snapshot BEFORE the compile-and-append critical section. When
    # the caller supplies one, use it verbatim (test fixtures + CLI
    # callers with a pre-built snapshot). Otherwise resolve the
    # workspace root from ``.ract`` ancestry and scan.
    resolved_workspace = workspace
    if resolved_workspace is None:
        project_dir = _resolve_project_dir(run_dir, ract_dir)
        if project_dir is not None:
            resolved_workspace = _scan_workspace_snapshot(project_dir)

    try:
        _sc_lock(lock_fd)
        try:
            return _recompile_intent_locked(
                run_dir=run_dir,
                intent_text=intent_text,
                operator_key=operator_key,
                run_dir_arg=run_dir,
                workspace=resolved_workspace,
            )
        finally:
            _sc_unlock(lock_fd)
    finally:
        os.close(lock_fd)


def _recompile_intent_locked(
    *,
    run_dir: Path,
    intent_text: str,
    operator_key: bytes,
    run_dir_arg: Path,
    workspace: "WorkspaceSnapshot | None" = None,
) -> RecompileResult:
    """Locked-scope body of :func:`recompile_intent`.

    Only :func:`recompile_intent` calls this; the split exists so the
    outer function owns the recompile-lock lifecycle explicitly.
    """
    # Deferred imports here (not in module scope) so the CLI verb's
    # ``argparse`` dispatch does not pull ``IntentCompiler`` unless
    # the recompile is actually happening.
    from ract.core.compile import IntentCompiler
    from ract.core.loop import load_suite_from_run_dir

    # Load the previous suite to pull the run_id from its canonical
    # serialisation. The run_id lives on the associated Rootknot chain
    # rather than the suite itself in v0.5.1; when a run_id.txt marker
    # is present we prefer that. Otherwise we derive a run_id from the
    # run_dir's basename which module_02's convention already uses.
    run_id_marker = run_dir / "run_id.txt"
    if run_id_marker.exists():
        run_id = run_id_marker.read_text(encoding="utf-8").strip()
    else:
        run_id = run_dir.name

    try:
        prev_suite = load_suite_from_run_dir(run_dir)
    except FileNotFoundError as exc:
        raise IntentRecompileError(
            f"run directory {run_dir} has no suite.json; cannot recompile "
            "a run that has not been compiled at least once"
        ) from exc

    # v0.5.1 wiring module_02 (Lens D D4): compile against a real
    # snapshot when one is available so ``_discover_test_files``
    # returns the actual test corpus and the fresh suite carries
    # required predicates. Callers supply ``workspace`` for tests +
    # deterministic runs; the outer scope materialises one from
    # disk when omitted. When we STILL land here with no snapshot
    # (workspace root unresolvable) we preserve the prior suite's
    # predicates verbatim so ``build_loop_state``'s zero-predicate
    # post-init check does not fire and T1 is not silently disabled.
    from ract.core.loop import WorkspaceSnapshot

    scan_ws = workspace if workspace is not None else WorkspaceSnapshot()
    try:
        compiler = IntentCompiler()
        compiled = compiler.compile(intent_text, scan_ws)
        # A DualAcceptanceSuite (companion path) exposes ``visible``
        # as the substrate suite; the raw ``AcceptanceSuite`` path
        # is the recompile default.
        if hasattr(compiled, "visible"):
            new_suite = compiled.visible  # type: ignore[union-attr]
        else:
            new_suite = compiled  # type: ignore[assignment]
    except Exception as exc:  # noqa: BLE001 -- surface any compile error
        raise IntentRecompileError(
            f"IntentCompiler.compile failed for the new intent text: {exc}"
        ) from exc

    # D4 second-line defence (SP Q5 amendment): the empty-snapshot
    # fallthrough is the ORIGINAL defect scenario -- fresh compile
    # produces ZERO required predicates and T1 becomes a silent
    # pass. Guard ONLY that case. A non-zero shrinkage (operator
    # legitimately retires a test) is honored -- otherwise the
    # defence would over-preserve and block a valid recompile flow.
    # SP feedback: an unconditional "smaller-than-prev" preserve
    # blocks legitimate operator removal; scope the guard to the
    # bright-line "zero required predicates" symptom.
    prev_required = tuple(p for p in prev_suite.predicates if getattr(p, "required", False))
    new_required = tuple(p for p in new_suite.predicates if getattr(p, "required", False))
    if len(new_required) == 0 and len(prev_required) > 0:
        _LOG.warning(
            "intent recompile: new compile yielded ZERO required predicates "
            "(prior suite had %d); preserving prior predicate set to keep "
            "T1 armed. This defends against the D4 empty-snapshot "
            "fallthrough; a legitimate removal path is a v0.6 CLI feature.",
            len(prev_required),
        )
        new_suite = AcceptanceSuite(
            intent_id=prev_suite.intent_id,
            predicates=prev_suite.predicates,
            coverage_gate=prev_suite.coverage_gate,
            compiled_from=new_suite.compiled_from,
            compiler_version=new_suite.compiler_version,
            prompt_digest=new_suite.prompt_digest,
        )

    if new_suite.prompt_digest is None:
        # Belt-and-suspenders: the compiler must populate this per
        # module_02, but a caller that swaps in a custom compiler
        # could break the invariant. Compute defensively.
        digest_bytes = bytes(compute_prompt_digest(intent_text))
        new_suite = AcceptanceSuite(
            intent_id=new_suite.intent_id,
            predicates=new_suite.predicates,
            coverage_gate=new_suite.coverage_gate,
            compiled_from=new_suite.compiled_from,
            compiler_version=new_suite.compiler_version,
            prompt_digest=digest_bytes,
        )

    prompt_digest_bytes = new_suite.prompt_digest
    assert prompt_digest_bytes is not None  # narrowed above

    suite_digest_hex = new_suite.digest()
    signature = _sign_recompile(
        operator_key, suite_digest_hex, prompt_digest_bytes, run_id
    )

    chain = SuiteChain(run_dir)

    # Ensure the initial suite is recorded as chain entry 0 the first
    # time a recompile runs. Without this the ancestor chain would
    # be missing its root.
    if not chain.entries() and prev_suite.prompt_digest is not None:
        chain.append(
            prompt_digest=prev_suite.prompt_digest,
            suite_digest=prev_suite.digest(),
            run_id=run_id,
            origin="initial",
            rootknot_signature=None,
        )

    entry = chain.append(
        prompt_digest=prompt_digest_bytes,
        suite_digest=suite_digest_hex,
        run_id=run_id,
        origin="operator_recompile",
        rootknot_signature=signature,
    )

    # Overwrite suite.json so a fresh loader picks up the new suite.
    suite_json_path = run_dir / "suite.json"
    suite_json_path.write_text(new_suite.to_json(), encoding="utf-8")

    _LOG.info(
        "intent recompile: run_id=%s new_prompt_digest=%s (chain now has %d entries)",
        run_id,
        prompt_digest_bytes.hex(),
        len(chain.entries()),
    )

    return RecompileResult(
        new_suite=new_suite,
        entry=entry,
        suite_chain_path=chain.path,
    )


# RACT 0.5.1
