"""B-028 (D-142): the pieces of the WSL2 and container backends that need neither bubblewrap nor an image.

LR:: A grant rule may say ``backend: wsl2`` (the program comes from WSL) or
``backend: container`` (it runs in an image pinned by digest). This module
holds what can be built and tested on this machine now:

- ``resolve_in_wsl``: the Linux program a ``wsl2`` rule names, found on
  WSL's PATH, and its SHA-256 read through ``\\\\wsl$`` so the prompt can show
  the Linux path and the grant can pin the file the operator approved.
- ``ContainerBackend``: the ``docker run`` argv for a command (network off,
  read-only root, the worktree at ``/workspace``) and whether the pinned
  image is already present. Nothing is pulled.

Neither runs a command for a rule yet: the WSL backend needs bubblewrap
inside WSL (row D4 on the operator's page) and its self-test, and the
container backend needs an image. Until then such rules are refused at run
(``tests_tool.run_under_rule``). Every process this module starts goes
through *run*, so tests use a fake and start no WSL and no Docker.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

Run = Callable[..., Any]


# Why a rule naming each backend does not run in this release (B-028, D-142).
NOT_WIRED = {
    "wsl2": "it needs bubblewrap inside WSL and its self-test (the operator's row D4)",
    "container": "it needs the pinned image on this machine and its self-test",
}


def why_not_wired(backend: str) -> str:
    """Why a rule naming *backend* does not run in this release."""
    return NOT_WIRED.get(backend, "this release knows no such backend")


class BackendUnavailable(RuntimeError):
    """The backend cannot do what was asked here; the message says why."""


@dataclass(frozen=True)
class WslProgram:
    distro: str
    linux_path: str
    unc_path: str
    sha256: str


def _text(out: Any) -> str:
    if isinstance(out, bytes):
        # wsl.exe prints its own messages in UTF-16.
        return out.decode("utf-16-le" if b"\x00" in out else "utf-8", errors="replace")
    return str(out or "")


def default_distro(*, run: Run = subprocess.run) -> str:
    """The distribution ``wsl.exe`` uses when none is named."""
    done = run(["wsl.exe", "--list", "--quiet"], capture_output=True, timeout=30)
    names = [n.strip().strip("\x00") for n in _text(done.stdout).splitlines()]
    names = [n for n in names if n]
    if done.returncode != 0 or not names:
        raise BackendUnavailable("WSL lists no distribution on this machine")
    return names[0]


def resolve_in_wsl(
    name: str,
    *,
    distro: str | None = None,
    run: Run = subprocess.run,
    read_bytes: Callable[[str], bytes] = lambda p: Path(p).read_bytes(),
) -> WslProgram:
    """Where *name* is inside WSL, and the SHA-256 of that file (D-142 answer 1)."""
    if not name or "/" in name and not name.startswith("/") or "\x00" in name:
        raise BackendUnavailable(f"{name!r} is not a program name or an absolute path")
    distro = distro or default_distro(run=run)
    done = run(
        ["wsl.exe", "-d", distro, "--", "sh", "-c", 'command -v -- "$1"', "sh", name],
        capture_output=True,
        timeout=30,
    )
    found = _text(done.stdout).strip()
    if done.returncode != 0 or not found.startswith("/"):
        raise BackendUnavailable(f"{name} is not on WSL's PATH in {distro}")
    posix = PurePosixPath(found)
    unc = "\\\\wsl$\\" + distro + "\\" + "\\".join(posix.parts[1:])
    try:
        digest = hashlib.sha256(read_bytes(unc)).hexdigest()
    except OSError as exc:
        raise BackendUnavailable(
            f"{found} in {distro} could not be read: {exc}"
        ) from exc
    return WslProgram(distro, str(posix), unc, digest)


@dataclass(frozen=True)
class ContainerBackend:
    """``docker run`` for a rule with ``backend: container`` (D-142 answer 3)."""

    image: str
    run: Run = subprocess.run
    name: str = "container"

    def image_present(self) -> bool:
        """True when the pinned image is already on this machine; nothing is pulled."""
        done = self.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", self.image],
            capture_output=True,
            timeout=30,
        )
        return done.returncode == 0

    def render(
        self, worktree: Path, argv: Sequence[str], *, network: bool = False
    ) -> list[str]:
        """The argv that runs *argv* in the image, the worktree at /workspace."""
        if not self.image_present():
            raise BackendUnavailable(
                f"the image {self.image} is not on this machine; RACT pulls nothing"
            )
        return [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network",
            "bridge" if network else "none",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "-v",
            f"{Path(worktree).resolve()}:/workspace",
            "-w",
            "/workspace",
            "-e",
            "HOME=/tmp",
            self.image,
            *argv,
        ]


__all__ = [
    "NOT_WIRED",
    "BackendUnavailable",
    "ContainerBackend",
    "WslProgram",
    "default_distro",
    "resolve_in_wsl",
    "why_not_wired",
]
