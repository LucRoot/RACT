"""Sandbox backend contract + platform dispatch.

SUBSTRATE spec §4. The concrete backends live in
``sandbox_linux.py`` (Bubblewrap + Landlock + seccomp-bpf; see
``https://github.com/containers/bubblewrap``, ``https://landlock.io/``,
and ``https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html``)
and ``sandbox_macos.py`` (Seatbelt / ``sandbox-exec``; see Apple's public
sandboxing documentation).

Windows currently has no equivalent primitive shipped here (lateral
chain branch A). ``resolve_backend`` returns a stub whose
``enter`` raises ``SandboxNotAvailable``. The loop refuses to run unless
the operator sets ``--allow-unenforced-sandbox``; when set, the flag is
stamped into every event and every run report.

The sandbox event is emitted at the call site
(``StepTransaction.open``). Module_05 defines the event log schema; this
module publishes ``SandboxEvent`` values into a callable sink so the
call site exists today even though the receiving log lands later.
"""

from __future__ import annotations

import platform
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Literal, Protocol

from ract.security.manifest import CapabilityManifest, ManifestDigest


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SandboxNotAvailable(RuntimeError):
    """Raised when the current platform has no OS-enforced sandbox shipped.

    On Windows this fires unless ``--allow-unenforced-sandbox`` is set on
    the run. The message names the platform and points at the escape
    hatch flag; the flag itself is loud in the event log.
    """


class SandboxViolation(RuntimeError):
    """Raised when the sandbox refuses an action at enter time.

    Runtime refusals (an inside-the-sandbox syscall killed by seccomp,
    a Landlock write-refusal) surface as process exit codes / SIGSYS at
    the operating system layer, not as Python exceptions. This exception
    is only raised for refusals visible to the harness during
    ``SandboxBackend.enter`` — e.g. a manifest that names a path the
    kernel Landlock version cannot enforce.
    """


# ---------------------------------------------------------------------------
# Event surface (call site exists today; log schema lands module_05)
# ---------------------------------------------------------------------------


EventName = Literal["sandbox.granted", "sandbox.denied", "sandbox.unenforced"]


@dataclass(frozen=True)
class SandboxEvent:
    """One sandbox call-site event.

    ``manifest_digest`` is the SHA256 hex of the canonical serialization
    (see ``ManifestDigest``); downstream modules join events to manifests
    via this digest.
    """

    name: EventName
    manifest_digest: str
    step_id_hex: str
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


EventSink = Callable[[SandboxEvent], None]


def _null_sink(event: SandboxEvent) -> None:
    """Default sink — drops events. Module_05 will replace this."""
    del event


_sink: EventSink = _null_sink


def set_event_sink(sink: EventSink) -> None:
    """Replace the module-level sink. Module_05's event log will call this."""
    global _sink
    _sink = sink


def emit(event: SandboxEvent) -> None:
    """Publish a sandbox event to the current sink."""
    _sink(event)


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------


class SandboxBackend(Protocol):
    """Contract every platform backend implements.

    ``enter`` returns a context manager. On enter it applies the
    manifest-derived policy (filesystem allowlist, network allowlist,
    seccomp profile, env scrub); on exit it tears the policy down. The
    backend is stateless across calls — the manifest carried in is the
    only input.
    """

    def enter(
        self,
        manifest: CapabilityManifest,
        worktree: Path,
        container: Any | None = None,
        *,
        step_id: bytes,
    ) -> Any:
        """Return a context manager scoping one step's OS-level policy."""
        ...

    @property
    def name(self) -> str:
        """Backend identifier (``linux-bwrap``, ``macos-sandbox-exec``, ``stub``)."""
        ...

    @property
    def enforced(self) -> bool:
        """True when the OS actually enforces the policy for this backend."""
        ...


# ---------------------------------------------------------------------------
# Windows / fallback stub
# ---------------------------------------------------------------------------


class UnenforcedSandbox:
    """Fallback backend for platforms without shipped OS enforcement.

    The stub emits ``sandbox.unenforced`` (loud in the event log) and
    yields control immediately. It exists so the call site in
    ``StepTransaction.open`` has something to invoke on Windows without
    forking the caller code on ``sys.platform``. The run report stamps
    ``sandbox_enforced=False`` when the stub is active.
    """

    name = "stub"
    enforced = False

    @contextmanager
    def enter(
        self,
        manifest: CapabilityManifest,
        worktree: Path,
        container: Any | None = None,
        *,
        step_id: bytes,
    ) -> Iterator[None]:
        digest_hex = ManifestDigest.of(manifest).hex()
        emit(
            SandboxEvent(
                name="sandbox.unenforced",
                manifest_digest=digest_hex,
                step_id_hex=step_id.hex(),
                reason=(
                    "no OS-enforced sandbox available on this platform; "
                    "running with --allow-unenforced-sandbox"
                ),
                details={"platform": platform.system(), "worktree": str(worktree)},
            )
        )
        yield


# ---------------------------------------------------------------------------
# Backend resolution
# ---------------------------------------------------------------------------


def resolve_backend(
    *,
    allow_unenforced: bool = False,
    platform_override: str | None = None,
) -> SandboxBackend:
    """Return the sandbox backend for the current platform.

    On Linux this returns a ``LinuxSandbox`` (requires ``bwrap`` on
    PATH; the constructor probes for it and falls back to raising
    ``SandboxNotAvailable`` if missing — this is the depth-chain
    "Bubblewrap-only namespace isolation" fallback path made explicit).

    On macOS this returns a ``MacosSandbox`` (requires ``sandbox-exec``
    on PATH — shipped on every supported macOS release).

    On Windows this raises ``SandboxNotAvailable`` unless
    ``allow_unenforced=True``, in which case it returns
    ``UnenforcedSandbox`` and the caller stamps the escape-hatch flag
    into the run report.

    ``platform_override`` exists solely so tests can drive the Windows
    branch on non-Windows CI (and vice versa) without monkeypatching
    ``platform.system``.
    """
    system = platform_override if platform_override is not None else platform.system()
    if system == "Linux":
        # Local import so a missing macOS-only backend doesn't crash the
        # Linux path on module import and vice versa.
        from ract.security.sandbox_linux import LinuxSandbox

        try:
            return LinuxSandbox()
        except SandboxNotAvailable:
            if allow_unenforced:
                return UnenforcedSandbox()
            raise
    if system == "Darwin":
        from ract.security.sandbox_macos import MacosSandbox

        try:
            return MacosSandbox()
        except SandboxNotAvailable:
            if allow_unenforced:
                return UnenforcedSandbox()
            raise
    # Windows and anything else fall through here.
    if allow_unenforced:
        return UnenforcedSandbox()
    raise SandboxNotAvailable(
        f"no OS-enforced sandbox shipped for platform {system!r}. Re-run "
        "with --allow-unenforced-sandbox to proceed under the fallback "
        "backend; the flag is loud in the event log and stamped into the "
        "run report."
    )


# RACT 0.4.0
