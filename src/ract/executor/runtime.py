"""Container backend shim for the substrate executor.

SUBSTRATE spec §3.2 (Container-per-worktree). This module lands the
``ContainerBackend`` protocol plus two implementations:

- ``DaggerBackend`` — cross-platform, delegates to the Dagger CLI. See
  the Dagger Container Use README at
  ``https://github.com/dagger/container-use`` for the pattern
  (one container per worktree, mounted read/write at a known path).
- ``PodmanBackend`` — falls back to ``docker`` when ``podman`` is not on
  PATH; the CLI-shaped API is identical.

Availability varies by platform (lateral chain branch A). On a bare
Windows machine neither Dagger nor Podman may be installed; that is
fine — this module's backends are only invoked when a plan step declares
``runtime_container``. A step without that field runs in the worktree
alone. The RACT tree therefore stays import-clean without either SDK on
disk; runtime failure is only observed when a live step actually asks
for a container.

Module_03 will land the OS-enforced sandbox (bwrap + Landlock + seccomp
on Linux, Seatbelt on macOS) **inside** the container the shim starts;
this module's contract is only that the container exists and mounts the
worktree at ``/workspace``.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ract.core.transaction import ContainerRef, ResourceBudget


class RuntimeError(Exception):  # noqa: N818 — keep the Pythonic name
    """Raised when a container backend fails or is unavailable."""


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------


class ContainerBackend(Protocol):
    """Minimal contract every backend implements.

    ``start`` returns a ``ContainerRef`` handle. ``stop`` accepts the
    handle and tears the container down. ``is_available`` returns True
    iff the backend's CLI is discoverable — the loop uses this to decide
    whether to skip container isolation on a platform where neither
    Dagger nor Podman is installed (lateral chain branch A).
    """

    name: str

    def is_available(self) -> bool: ...

    def start(
        self,
        *,
        image: str,
        worktree_path: Path,
        budget: ResourceBudget,
    ) -> ContainerRef: ...

    def stop(self, ref: ContainerRef) -> None: ...


# ---------------------------------------------------------------------------
# CLI-shaped helpers
# ---------------------------------------------------------------------------


def _which_first(*candidates: str) -> str | None:
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path
    return None


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a subprocess capturing text output. Never raises on non-zero."""
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


# ---------------------------------------------------------------------------
# Dagger backend
# ---------------------------------------------------------------------------


@dataclass
class DaggerBackend:
    """Dagger CLI shim.

    Uses the ``dagger`` CLI shape (``dagger run …``) so RACT stays
    independence-lint-clean — we never depend on ``dagger-io`` at import
    time. The container-per-worktree pattern is documented in the Dagger
    Container Use README (cited in the module docstring).
    """

    name: str = "dagger"

    def is_available(self) -> bool:
        return _which_first("dagger") is not None

    def start(
        self,
        *,
        image: str,
        worktree_path: Path,
        budget: ResourceBudget,
    ) -> ContainerRef:
        if not self.is_available():
            raise RuntimeError(
                "dagger CLI not found on PATH; install Dagger or route this "
                "step through PodmanBackend / no-container mode"
            )
        # Assign a stable id so ``stop`` can find it; the real container
        # id is opaque to us until Dagger emits it, so we surface the
        # RACT-side handle instead. Live invocation shape is intentionally
        # kept in ``_start_cmd`` so tests can assert against it without
        # spawning a container.
        rid = f"dagger-{uuid.uuid4().hex[:12]}"
        cmd = self._start_cmd(
            container_id=rid, image=image, worktree_path=worktree_path, budget=budget
        )
        result = _run(cmd)
        if result.returncode != 0:
            raise RuntimeError(
                f"dagger start failed for {rid}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return ContainerRef(backend=self.name, id=rid, image=image)

    def stop(self, ref: ContainerRef) -> None:
        if not self.is_available():
            # If the CLI vanished between start and stop, silently no-op;
            # the worktree teardown will still fire, so leaked state is
            # observable off disk rather than swallowed.
            return
        result = _run(["dagger", "container", "stop", ref.id])
        # ``stop`` returning non-zero is not fatal — the container may have
        # exited on its own. The rollback path still runs.
        if result.returncode != 0 and "no such container" not in (
            result.stderr + result.stdout
        ):
            raise RuntimeError(
                f"dagger stop failed for {ref.id}: {result.stderr.strip()}"
            )

    # Split out so tests can assert on the exact CLI shape without a live
    # Dagger install.
    def _start_cmd(
        self,
        *,
        container_id: str,
        image: str,
        worktree_path: Path,
        budget: ResourceBudget,
    ) -> list[str]:
        return [
            "dagger",
            "run",
            "--image",
            image,
            "--name",
            container_id,
            "--mount",
            f"{worktree_path}:/workspace",
            "--cpu",
            str(budget.cpu),
            "--memory",
            f"{budget.memory_mb}m",
            *(["--network", "none"] if not budget.network else []),
        ]


# ---------------------------------------------------------------------------
# Podman / Docker backend
# ---------------------------------------------------------------------------


@dataclass
class PodmanBackend:
    """Podman shim; falls back to docker if podman is not on PATH.

    Same CLI-shaped surface as ``DaggerBackend`` so a step can retarget
    backends without changing its plan.
    """

    name: str = "podman"

    def _cli(self) -> str | None:
        return _which_first("podman", "docker")

    def is_available(self) -> bool:
        return self._cli() is not None

    def start(
        self,
        *,
        image: str,
        worktree_path: Path,
        budget: ResourceBudget,
    ) -> ContainerRef:
        cli = self._cli()
        if cli is None:
            raise RuntimeError(
                "neither podman nor docker on PATH; install one or route "
                "this step through DaggerBackend / no-container mode"
            )
        rid = f"podman-{uuid.uuid4().hex[:12]}"
        cmd = self._start_cmd(
            cli=cli,
            container_id=rid,
            image=image,
            worktree_path=worktree_path,
            budget=budget,
        )
        result = _run(cmd)
        if result.returncode != 0:
            raise RuntimeError(
                f"{cli} run failed for {rid}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return ContainerRef(backend=self.name, id=rid, image=image)

    def stop(self, ref: ContainerRef) -> None:
        cli = self._cli()
        if cli is None:
            return
        result = _run([cli, "rm", "-f", ref.id])
        if result.returncode != 0 and "no such container" not in (
            result.stderr + result.stdout
        ):
            raise RuntimeError(f"{cli} rm failed for {ref.id}: {result.stderr.strip()}")

    def _start_cmd(
        self,
        *,
        cli: str,
        container_id: str,
        image: str,
        worktree_path: Path,
        budget: ResourceBudget,
    ) -> list[str]:
        parts = [
            cli,
            "run",
            "-d",
            "--name",
            container_id,
            "-v",
            f"{worktree_path}:/workspace",
            "--cpus",
            str(budget.cpu),
            "--memory",
            f"{budget.memory_mb}m",
        ]
        if not budget.network:
            parts.extend(["--network", "none"])
        parts.append(image)
        return parts


# RACT 0.4.0
