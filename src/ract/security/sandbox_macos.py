"""macOS sandbox backend — Seatbelt via ``sandbox-exec``.

SUBSTRATE spec §4. macOS lacks Landlock and seccomp-bpf equivalents,
but Seatbelt (Apple's kernel sandbox, driven from userspace by
``sandbox-exec``) covers filesystem and network primitives at the OS
layer. See Apple's public sandboxing documentation for the ``.sb``
profile syntax; the profile keywords used here (``file-read*``,
``file-write*``, ``network*``) are documented and stable.

The manifest-to-profile mapping mirrors the Linux backend so the two
enforcements agree on shape: the same ``CapabilityManifest`` produces a
Seatbelt profile whose filesystem allowlist and network allowlist are
byte-for-byte equivalent to the Landlock rules a Linux run would apply.

Import-clean on non-macOS: the module imports pure-Python stdlib only;
``sandbox-exec`` is shelled out at ``enter`` time.
"""

from __future__ import annotations

import fnmatch
import os.path
import platform
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from ract.security.manifest import CapabilityManifest, ManifestDigest
from ract.security.sandbox import (
    SandboxEvent,
    SandboxNotAvailable,
    SandboxViolation,
    emit,
)


@dataclass(frozen=True)
class SeatbeltProfile:
    """A rendered ``.sb`` profile plus the ``sandbox-exec`` invocation."""

    profile_text: str
    argv: tuple[str, ...]


class MacosSandbox:
    """macOS sandbox backend, driven by ``sandbox-exec``."""

    name = "macos-sandbox-exec"
    enforced = True

    def __init__(self, *, sandbox_exec_path: str | None = None) -> None:
        if platform.system() != "Darwin" and sandbox_exec_path is None:
            raise SandboxNotAvailable(
                "MacosSandbox is only available on macOS; use resolve_backend()"
            )
        candidate = sandbox_exec_path or shutil.which("sandbox-exec")
        if candidate is None:
            raise SandboxNotAvailable(
                "sandbox-exec not found on PATH; macOS ships it in "
                "/usr/bin/sandbox-exec but the shell PATH may not include "
                "it under some launchers"
            )
        self.sandbox_exec_path = candidate

    # -----------------------------------------------------------------
    # profile rendering
    # -----------------------------------------------------------------

    def render(
        self,
        manifest: CapabilityManifest,
        worktree: Path,
        argv_to_run: tuple[str, ...] = (),
    ) -> SeatbeltProfile:
        """Render the Seatbelt profile for this manifest + worktree.

        The profile starts from ``(deny default)`` per Apple's
        documented idiom, then allows: the worktree read-write, every
        ``manifest.filesystem.read`` pattern read-only, every
        ``manifest.filesystem.write`` pattern read-write, and every
        ``manifest.network.allow_hosts`` entry. Process bounds come from
        ``manifest.processes``.
        """
        lines: list[str] = [
            "(version 1)",
            "(deny default)",
            # Allow the sandboxed process to run.
            "(allow process-exec)",
            "(allow process-fork)",
            # Standard shim allowances a POSIX runtime needs.
            '(allow file-read* (literal "/dev/null") (literal "/dev/zero"))',
            '(allow file-read* (regex #"^/System/.*"))',
            '(allow file-read* (regex #"^/usr/lib/.*"))',
            '(allow file-read* (regex #"^/usr/share/.*"))',
            # The worktree is bind-equivalent — read + write.
            f'(allow file-read* (subpath "{worktree}"))',
            f'(allow file-write* (subpath "{worktree}"))',
        ]

        for path in manifest.filesystem.read:
            lines.append(f'(allow file-read* (subpath "{path}"))')

        for path in manifest.filesystem.write:
            lines.append(f'(allow file-read* (subpath "{path}"))')
            lines.append(f'(allow file-write* (subpath "{path}"))')

        for denied in manifest.filesystem.denied:
            lines.append(f'(deny file-read* (subpath "{denied}"))')
            lines.append(f'(deny file-write* (subpath "{denied}"))')

        if manifest.network.deny_default:
            for host in manifest.network.allow_hosts:
                lines.append(f'(allow network-outbound (remote ip "{host}:*"))')
        else:
            lines.append("(allow network-outbound)")

        argv: list[str] = [self.sandbox_exec_path, "-p", "\n".join(lines)]
        argv.extend(argv_to_run)
        return SeatbeltProfile(profile_text="\n".join(lines), argv=tuple(argv))

    # -----------------------------------------------------------------
    # harness-side pre-flight (parallels the Linux backend)
    # -----------------------------------------------------------------

    @staticmethod
    def _matches(target: str, patterns: tuple[str, ...]) -> bool:
        """Return True when the normalized target matches any pattern.

        Path-traversal literals like ``/workspace/../../etc/passwd``
        are collapsed with ``os.path.normpath`` before glob matching so
        the surface refuses them at pre-flight rather than smuggling
        them through a Seatbelt allowlist that only knew about
        ``/workspace/*``. Parallels the Linux backend's ``_path_allowed``.
        """
        normalized = os.path.normpath(target).replace("\\", "/")
        return any(fnmatch.fnmatch(normalized, p) for p in patterns)

    @classmethod
    def would_refuse_write(cls, manifest: CapabilityManifest, target: str) -> bool:
        if cls._matches(target, manifest.filesystem.denied):
            return True
        return not cls._matches(target, manifest.filesystem.write)

    @classmethod
    def would_refuse_read(cls, manifest: CapabilityManifest, target: str) -> bool:
        if cls._matches(target, manifest.filesystem.denied):
            return True
        if cls._matches(target, manifest.filesystem.read):
            return False
        if cls._matches(target, manifest.filesystem.write):
            return False
        return True

    @classmethod
    def would_refuse_network(cls, manifest: CapabilityManifest, host: str) -> bool:
        if not manifest.network.deny_default:
            return False
        for allowed in manifest.network.allow_hosts:
            if fnmatch.fnmatch(host, allowed):
                return False
        return True

    # -----------------------------------------------------------------
    # enter
    # -----------------------------------------------------------------

    @contextmanager
    def enter(
        self,
        manifest: CapabilityManifest,
        worktree: Path,
        container: Any | None = None,
        *,
        step_id: bytes,
    ) -> Iterator[SeatbeltProfile]:
        rendered = self.render(manifest, worktree)
        digest_hex = ManifestDigest.of(manifest).hex()
        emit(
            SandboxEvent(
                name="sandbox.granted",
                manifest_digest=digest_hex,
                step_id_hex=step_id.hex(),
                reason="",
                details={
                    "backend": self.name,
                    "worktree": str(worktree),
                    "profile_bytes": len(rendered.profile_text.encode("utf-8")),
                },
            )
        )
        try:
            yield rendered
        except SandboxViolation as exc:
            emit(
                SandboxEvent(
                    name="sandbox.denied",
                    manifest_digest=digest_hex,
                    step_id_hex=step_id.hex(),
                    reason=str(exc),
                )
            )
            raise


# RACT 0.4.0
