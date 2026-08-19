"""Per-repo fingerprint (module_08 step 7).

Each repo builds a fingerprint over time: average function length,
typical import depth, LSP response-time distribution, test-suite
runtime, commit frequency. The fingerprint feeds retrieval defaults
via a small pure-function mapper (repos with slow LSPs get more
aggressive caching; repos with large functions get larger neighborhood
budgets).

Design notes:

- ``compute`` handles the fresh-repo case (Lateral Chain branch D
  from module_08.md PRE) by returning ``-1`` sentinel values for
  fields the current session has no history to populate (LSP
  response times, test runtime). The mapper treats ``-1`` as "no
  signal, use module_01 spec defaults".
- ``compute`` is pure over ``(symbols, graph, git_log_output)`` —
  the git-log invocation is behind a small helper the caller can
  override in tests. This gives the "same fingerprint always maps
  to same defaults" invariant the Second Pass Q3 checks for.
- ``write`` uses tmp + fsync + ``os.replace`` for atomic replacement
  (Second Pass Q4).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot


FINGERPRINT_RECORD_PATH: Path = Path(".rack") / "fingerprint" / "repo.json"
"""Relative location of the shipped fingerprint record."""

FINGERPRINT_SCHEMA_VERSION: int = 1
"""Schema version for the JSON record. Bumped when the payload shape changes."""

NO_SIGNAL_SENTINEL: int = -1
"""Value the mapper treats as "no measurement available, use spec defaults"."""


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoFingerprint:
    """Fingerprint of one repo at one point in time.

    All fields carry the ``NO_SIGNAL_SENTINEL`` (``-1``) when the
    current session has no data to populate them (fresh repo, LSP
    not yet run, tests not yet timed). The mapper documented under
    :func:`retrieval_defaults_from_fingerprint` treats sentinels
    as "use module_01 spec defaults".
    """

    avg_function_tokens: float
    avg_import_depth: float
    lsp_response_time_p50_ms: int
    lsp_response_time_p95_ms: int
    test_suite_runtime_seconds: int
    commit_frequency_per_week: float
    recorded_at: int
    schema_version: int = FINGERPRINT_SCHEMA_VERSION


@dataclass(frozen=True)
class RetrievalDefaults:
    """Retrieval defaults derived from a fingerprint.

    Fields feed the module_05 retrieve primitive's per-call knobs.
    ``None`` means "let the retrieve primitive keep its own default".
    The mapper is a pure function of the fingerprint (Second Pass
    Q3 invariant).
    """

    cache_ttl_seconds: int | None
    neighborhood_max_symbols: int | None
    per_symbol_target_tokens: int | None


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------


def compute(
    root: Path,
    *,
    symbols: Any | None = None,
    graph: Any | None = None,
    lsp_response_times_ms: list[int] | None = None,
    test_suite_runtime_seconds: int | None = None,
    commit_timestamps: list[int] | None = None,
    now: int | None = None,
) -> RepoFingerprint:
    """Compute a fingerprint for the repo at ``root``.

    Parameters:

    - ``symbols`` — a :class:`~ract.memory.symbol_index.SymbolIndex`
      or ``None``. When present, ``avg_function_tokens`` is the
      mean of ``token_count`` over function / method rows with a
      non-null token count.
    - ``graph`` — a :class:`~ract.memory.graph_index.GraphIndex` or
      ``None``. When present, ``avg_import_depth`` is the mean count
      of ``imports`` edges per file in the graph.
    - ``lsp_response_times_ms`` — recent LSP round-trip samples in
      milliseconds. When ``None`` or empty, both p50 and p95
      fields carry :data:`NO_SIGNAL_SENTINEL`.
    - ``test_suite_runtime_seconds`` — most recent measured runtime
      of the repo's test suite. ``None`` collapses to the sentinel.
    - ``commit_timestamps`` — explicit list of POSIX-second commit
      timestamps (test injection). When ``None`` the function
      invokes ``git log --format=%at --since=4.weeks.ago`` under
      ``root`` and parses the output. Any invocation error
      collapses to the sentinel.

    The function is pure over the SUM of inputs: same inputs always
    produce the same output. The default git-log path is behind
    ``commit_timestamps=None``; callers who want strict determinism
    (tests) pass an explicit list.
    """
    fresh_now = int(now if now is not None else time.time())
    avg_function_tokens = _avg_function_tokens(symbols)
    avg_import_depth = _avg_import_depth(graph)
    p50, p95 = _lsp_percentiles(lsp_response_times_ms)
    test_runtime = (
        int(test_suite_runtime_seconds)
        if test_suite_runtime_seconds is not None
        else NO_SIGNAL_SENTINEL
    )
    commit_frequency = _commit_frequency_per_week(root, commit_timestamps)
    return RepoFingerprint(
        avg_function_tokens=avg_function_tokens,
        avg_import_depth=avg_import_depth,
        lsp_response_time_p50_ms=p50,
        lsp_response_time_p95_ms=p95,
        test_suite_runtime_seconds=test_runtime,
        commit_frequency_per_week=commit_frequency,
        recorded_at=fresh_now,
    )


def _avg_function_tokens(symbols: Any | None) -> float:
    """Return mean token_count over function / method rows, or 0.0.

    Fresh-repo path: an empty symbol index (or ``None``) returns
    ``0.0``. Callers of :func:`retrieval_defaults_from_fingerprint`
    treat ``0.0`` as "no signal".
    """
    if symbols is None:
        return 0.0
    conn = getattr(symbols, "connection", None)
    if conn is None:
        return 0.0
    cur = conn.execute(
        "SELECT AVG(token_count) AS avg_tokens FROM symbols "
        "WHERE kind IN ('function', 'method') AND token_count IS NOT NULL"
    )
    row = cur.fetchone()
    if row is None or row["avg_tokens"] is None:
        return 0.0
    return float(row["avg_tokens"])


def _avg_import_depth(graph: Any | None) -> float:
    """Return mean number of 'imports' edges per file in the graph.

    Fresh-repo path: empty graph or ``None`` returns ``0.0``.
    """
    if graph is None:
        return 0.0
    conn = getattr(graph, "connection", None)
    if conn is None:
        return 0.0
    cur = conn.execute(
        "SELECT COUNT(*) AS import_count, "
        "COUNT(DISTINCT location_file) AS file_count "
        "FROM edges WHERE edge_type = 'imports' "
        "AND location_file IS NOT NULL"
    )
    row = cur.fetchone()
    if row is None:
        return 0.0
    import_count = row["import_count"] or 0
    file_count = row["file_count"] or 0
    if file_count == 0:
        return 0.0
    return float(import_count) / float(file_count)


def _lsp_percentiles(samples: list[int] | None) -> tuple[int, int]:
    """Return ``(p50_ms, p95_ms)`` or ``(-1, -1)`` on empty input."""
    if not samples:
        return (NO_SIGNAL_SENTINEL, NO_SIGNAL_SENTINEL)
    sorted_samples = sorted(int(sample) for sample in samples)
    p50 = _percentile(sorted_samples, 0.50)
    p95 = _percentile(sorted_samples, 0.95)
    return (p50, p95)


def _percentile(sorted_samples: list[int], q: float) -> int:
    """Return the integer nearest-rank percentile of ``sorted_samples``.

    Nearest-rank rather than linear interpolation because callers
    compare against integer ms thresholds (100 ms, 250 ms) and an
    interpolated float would need re-rounding at the compare site.
    """
    if not sorted_samples:
        return NO_SIGNAL_SENTINEL
    if q <= 0:
        return sorted_samples[0]
    if q >= 1:
        return sorted_samples[-1]
    rank = max(0, int(round(q * len(sorted_samples))) - 1)
    return sorted_samples[rank]


def _commit_frequency_per_week(
    root: Path,
    commit_timestamps: list[int] | None,
) -> float:
    """Return commits per week over the last four weeks, or 0.0.

    Fresh-repo path: a repo with no commits or a git invocation
    that fails collapses to ``0.0`` (not the sentinel, because zero
    is a legitimate observation on a brand-new repo).
    """
    if commit_timestamps is not None:
        if not commit_timestamps:
            return 0.0
        return float(len(commit_timestamps)) / 4.0
    if not (root / ".git").exists():
        return 0.0
    try:
        completed = subprocess.run(
            ["git", "log", "--format=%at", "--since=4.weeks.ago"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0.0
    if completed.returncode != 0:
        return 0.0
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    return float(len(lines)) / 4.0


# ---------------------------------------------------------------------------
# Mapper (pure)
# ---------------------------------------------------------------------------


def retrieval_defaults_from_fingerprint(
    fingerprint: RepoFingerprint,
) -> RetrievalDefaults:
    """Return retrieval defaults derived from ``fingerprint``.

    Pure function: same fingerprint always produces the same defaults
    (Second Pass Q3 invariant). Sentinels (``-1``) collapse to
    ``None`` so the retrieve primitive keeps its own module_05
    defaults.

    Heuristics:

    - Slow LSPs (p95 > 250 ms): raise ``cache_ttl_seconds`` to
      600 s so retrieve avoids re-invoking the LSP on every call.
    - Fast LSPs (p95 <= 250 ms): shorter TTL (60 s) so a code change
      does not linger in cache.
    - Large functions (avg_function_tokens > 400): raise
      ``per_symbol_target_tokens`` to 800 so a typical function
      fits at FULL format.
    - Small functions (avg_function_tokens <= 400) or no signal:
      leave ``None`` to inherit module_05 default.
    - High import depth (avg > 10): reduce
      ``neighborhood_max_symbols`` to 15 so the neighborhood does
      not explode; low depth keeps None.
    """
    cache_ttl_seconds: int | None = None
    if fingerprint.lsp_response_time_p95_ms != NO_SIGNAL_SENTINEL:
        cache_ttl_seconds = 600 if fingerprint.lsp_response_time_p95_ms > 250 else 60

    per_symbol_target_tokens: int | None = None
    if fingerprint.avg_function_tokens > 400.0:
        per_symbol_target_tokens = 800

    neighborhood_max_symbols: int | None = None
    if fingerprint.avg_import_depth > 10.0:
        neighborhood_max_symbols = 15

    return RetrievalDefaults(
        cache_ttl_seconds=cache_ttl_seconds,
        neighborhood_max_symbols=neighborhood_max_symbols,
        per_symbol_target_tokens=per_symbol_target_tokens,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def write(fingerprint: RepoFingerprint, root: Path) -> Path:
    """Write ``fingerprint`` atomically under ``root``.

    Path resolves as ``root / FINGERPRINT_RECORD_PATH``. Parent
    directories are created on demand. Atomic-replace via tmp +
    fsync + ``os.replace`` (Second Pass Q4).
    """
    target = root / FINGERPRINT_RECORD_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(fingerprint)
    text = json.dumps(payload, sort_keys=True, separators=(",", ": ")) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix="fingerprint-",
        suffix=".json.tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return target


def read(root: Path) -> RepoFingerprint | None:
    """Return the fingerprint stored under ``root`` or ``None``.

    ``None`` on missing file (fresh install). Raises
    :class:`ValueError` on malformed JSON or unsupported schema
    version — a corrupted file surfaces loudly rather than
    silently reverting to spec defaults.
    """
    target = root / FINGERPRINT_RECORD_PATH
    if not target.is_file():
        return None
    text = target.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"fingerprint record at {target} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(
            f"fingerprint record at {target} must be a JSON object; "
            f"got {type(payload).__name__}"
        )
    schema_version = payload.get("schema_version")
    if schema_version != FINGERPRINT_SCHEMA_VERSION:
        raise ValueError(
            f"fingerprint record at {target} has unsupported schema_version "
            f"{schema_version!r}; expected {FINGERPRINT_SCHEMA_VERSION!r}"
        )
    required_int = (
        "lsp_response_time_p50_ms",
        "lsp_response_time_p95_ms",
        "test_suite_runtime_seconds",
        "recorded_at",
    )
    required_float = (
        "avg_function_tokens",
        "avg_import_depth",
        "commit_frequency_per_week",
    )
    for key in required_int:
        if (
            key not in payload
            or not isinstance(payload[key], int)
            or isinstance(payload[key], bool)
        ):
            raise ValueError(
                f"fingerprint record field {key!r} must be int; "
                f"got {payload.get(key)!r}"
            )
    for key in required_float:
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(
                f"fingerprint record field {key!r} must be numeric; got {value!r}"
            )
    return RepoFingerprint(
        avg_function_tokens=float(payload["avg_function_tokens"]),
        avg_import_depth=float(payload["avg_import_depth"]),
        lsp_response_time_p50_ms=payload["lsp_response_time_p50_ms"],
        lsp_response_time_p95_ms=payload["lsp_response_time_p95_ms"],
        test_suite_runtime_seconds=payload["test_suite_runtime_seconds"],
        commit_frequency_per_week=float(payload["commit_frequency_per_week"]),
        recorded_at=payload["recorded_at"],
        schema_version=schema_version,
    )


__all__ = [
    "FINGERPRINT_RECORD_PATH",
    "FINGERPRINT_SCHEMA_VERSION",
    "NO_SIGNAL_SENTINEL",
    "RepoFingerprint",
    "RetrievalDefaults",
    "compute",
    "read",
    "retrieval_defaults_from_fingerprint",
    "write",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
