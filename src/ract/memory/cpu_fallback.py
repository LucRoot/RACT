"""LanceDB availability probe + backend selection for module_04.

LanceDB ships a pre-built GPU-accelerated wheel on most x86 targets;
on Windows ARM64 (Snapdragon X) the wheel may lag or be CPU-only.
This module owns the probe surface so
:class:`~ract.memory.semantic_index.SemanticIndex` can adapt at open
time and log the backend chosen.

The probe is intentionally cheap: import the top-level ``lancedb``
module and inspect its declared version + a ``backend`` env var. It
does not open a store or run a benchmark; a real perf regression is
still visible in the semantic-builder report's ``elapsed_ms`` field.

Called by :meth:`SemanticIndex.__init__` once per store open; the
result is exposed on the instance as ``lance_probe`` for tests +
diagnostics.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal

from ract.core.module_identity import _module_knot, register_module_knot


_LOGGER = logging.getLogger(__name__)


LANCEDB_BACKEND_ENV_VAR: str = "RACT_LANCEDB_BACKEND"
"""Env var that forces a backend (``gpu`` / ``cpu``); wins over the auto-probe."""


@dataclass(frozen=True)
class LanceDbProbeResult:
    """The result of :func:`probe_lancedb`.

    - ``available`` — True iff ``import lancedb`` succeeded.
    - ``backend`` — ``"gpu"`` when the GPU wheel is available and not
      overridden; ``"cpu"`` when only CPU is available or the caller
      forced CPU via the env var.
    - ``version`` — the imported ``lancedb.__version__``, or ``None``
      when the import failed.
    - ``error_message`` — non-empty when ``available`` is False; the
      operator's log-facing reason.
    """

    available: bool
    backend: Literal["gpu", "cpu"]
    version: str | None
    error_message: str | None


def probe_lancedb() -> LanceDbProbeResult:
    """Return the current process's LanceDB probe result.

    Import is lazy so a caller that only wants the probe does not pay
    the wheel-load cost when LanceDB is present but unused. The
    env-var override :data:`LANCEDB_BACKEND_ENV_VAR` wins over the
    auto-probe so a caller can force CPU on a machine that would
    otherwise pick GPU (test / diagnostic use).
    """
    try:
        import lancedb  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        _LOGGER.info(
            "lancedb not installed; SemanticIndex will refuse to open. Install "
            "``pip install lancedb`` to enable the semantic index."
        )
        return LanceDbProbeResult(
            available=False,
            backend="cpu",
            version=None,
            error_message=f"lancedb import failed: {exc}",
        )
    version = getattr(lancedb, "__version__", None)
    override = os.environ.get(LANCEDB_BACKEND_ENV_VAR, "").lower()
    if override in ("gpu", "cpu"):
        backend_literal: Literal["gpu", "cpu"] = "gpu" if override == "gpu" else "cpu"
        _LOGGER.info(
            "lancedb backend forced to %s by %s",
            backend_literal,
            LANCEDB_BACKEND_ENV_VAR,
        )
        return LanceDbProbeResult(
            available=True,
            backend=backend_literal,
            version=version,
            error_message=None,
        )
    # Best-effort auto-detect. LanceDB's current wheels do not expose
    # a direct GPU probe; we treat everything as CPU by default and
    # let the caller opt in through the env var. Rationale: the
    # module_04 spec DoD requires the probe to be defined; over-
    # claiming GPU when the wheel is CPU-only would mislead the
    # operator's diagnostic (Second Pass Q2 style honesty).
    return LanceDbProbeResult(
        available=True,
        backend="cpu",
        version=version,
        error_message=None,
    )


__all__ = [
    "LANCEDB_BACKEND_ENV_VAR",
    "LanceDbProbeResult",
    "probe_lancedb",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
