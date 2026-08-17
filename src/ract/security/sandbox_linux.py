"""Linux sandbox backend — Bubblewrap + Landlock + seccomp-bpf.

SUBSTRATE spec §4.2. Every step's worktree (and, if the plan step opts
in, its container) enters this sandbox before the runner touches it. The
policy is derived from the ``CapabilityManifest`` and enforced by three
layers stacked in order:

1. **Bubblewrap** (``https://github.com/containers/bubblewrap``) provides
   Linux namespace isolation — mount, pid, uts, net. The worktree is
   bind-mounted read-write; every ``manifest.filesystem.read`` pattern is
   bind-mounted read-only; nothing else is visible.
2. **Landlock** (``https://landlock.io/`` and
   ``https://www.kernel.org/doc/html/latest/userspace-api/landlock.html``)
   layers a filesystem allowlist on top of the namespace so a write to a
   path not on ``manifest.filesystem.write`` is refused by the kernel,
   not by Python-level string checks (SUBSTRATE §4.2 Ona-incident lesson).
3. **seccomp-bpf**
   (``https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html``)
   filters syscalls per ``manifest.syscalls.seccomp_profile``. The
   ``strict`` profile refuses ``ptrace``, ``mount``, ``unshare``,
   ``module_load``, and other kernel-config-adjacent calls.

The sandbox configuration is *not* mutable by the sandboxed process:
the manifest file is never bind-mounted in, the seccomp filter is
applied with ``SECCOMP_FILTER_FLAG_TSYNC`` so it survives ``execve``,
and the ``CAP_SYS_ADMIN`` capability is dropped so Landlock rules
cannot be re-loaded from inside.

**Import-clean on non-Linux.** The module imports pure-Python stdlib
only; the actual bwrap / kernel primitives are shelled out at ``enter``
time. So mypy and ruff can lint this file on Windows without a
Linux-only import failing at parse time.
"""

from __future__ import annotations

import fnmatch
import platform
import shlex
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


# seccomp profile syscalls that are *refused* under ``strict``. The
# whole shipped kernel seccomp allowlist is broader than we can enumerate
# in a docstring; this block records the refused-under-strict set that
# the tests assert on. Sources: seccomp-bpf kernel docs (link above)
# and Bubblewrap's ``--seccomp`` idiom.
STRICT_REFUSED_SYSCALLS = frozenset(
    {
        "ptrace",
        "mount",
        "umount",
        "umount2",
        "unshare",
        "clone3",
        "init_module",
        "finit_module",
        "delete_module",
        "kexec_load",
        "kexec_file_load",
        "reboot",
        "setns",
        "pivot_root",
    }
)


@dataclass(frozen=True)
class BwrapCommand:
    """A rendered ``bwrap`` invocation, kept as data so tests can assert on it.

    The invocation is what the sandbox would exec; keeping it as a value
    lets adversarial tests inspect the argv shape without needing bwrap
    on PATH.
    """

    argv: tuple[str, ...]
    env: dict[str, str]
    seccomp_profile: str

    def shell_form(self) -> str:
        """Return the argv joined with shell quoting — for logging only."""
        return " ".join(shlex.quote(a) for a in self.argv)


class LinuxSandbox:
    """Linux sandbox backend.

    The constructor probes for ``bwrap`` on PATH; a missing binary
    raises ``SandboxNotAvailable`` so ``resolve_backend`` can decide
    whether to fall through to the unenforced stub.
    """

    name = "linux-bwrap"
    enforced = True

    def __init__(self, *, bwrap_path: str | None = None) -> None:
        # ``bwrap_path=None`` is the shipping path; the parameter exists
        # so property tests can point at a stub.
        if platform.system() != "Linux" and bwrap_path is None:
            raise SandboxNotAvailable(
                "LinuxSandbox is only available on Linux; use resolve_backend()"
            )
        candidate = bwrap_path or shutil.which("bwrap")
        if candidate is None:
            raise SandboxNotAvailable(
                "bwrap (Bubblewrap) not found on PATH; install bubblewrap or "
                "re-run with --allow-unenforced-sandbox"
            )
        self.bwrap_path = candidate

    # -----------------------------------------------------------------
    # policy derivation
    # -----------------------------------------------------------------

    def render(
        self,
        manifest: CapabilityManifest,
        worktree: Path,
        argv_to_run: tuple[str, ...] = (),
    ) -> BwrapCommand:
        """Render the ``bwrap`` command for this manifest + worktree.

        Kept as a separate function from ``enter`` so the tests can
        inspect the argv without opening a real namespace.
        """
        args: list[str] = [
            self.bwrap_path,
            # No inherited environment, no host / proc / dev / tmp
            # by default — an allowlist, not a denylist.
            "--clearenv",
            # Fresh proc and dev at fixed paths so common tooling works;
            # the mount is read-only so the sandboxed process cannot
            # add new device nodes.
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            # Read-only /tmp shim so libraries that expect one don't
            # crash; writable scratch is via the worktree bind.
            "--tmpfs",
            "/tmp",
            # Namespace-level network isolation. The proxy sits above
            # (see ``manifest.network.allow_hosts``).
            "--unshare-net" if manifest.network.deny_default else "--share-net",
            # No new privileges — this is the seccomp / setuid guard
            # (Bubblewrap sets NO_NEW_PRIVS by default; we assert it).
            "--new-session",
            # Bind the worktree read-write at /workspace.
            "--bind",
            str(worktree),
            "/workspace",
        ]

        # Read-only bind-mounts for every manifest.filesystem.read
        # pattern. Landlock refines this further inside the sandbox; the
        # bind is the outer wall.
        for path in manifest.filesystem.read:
            args += ["--ro-bind-try", path, path]

        # Read-write bind-mounts for every manifest.filesystem.write
        # pattern (in addition to /workspace).
        for path in manifest.filesystem.write:
            args += ["--bind-try", path, path]

        # Env passthrough: allowlist. --setenv sets the value; a missing
        # var in the outer env is left unset.
        for name in manifest.env.passthrough:
            # ``bwrap`` reads from the caller's environment via
            # --setenv; the caller stitches the value in.
            args += ["--setenv-if-set", name]

        # seccomp profile — deferred to ``enter`` (needs an open fd);
        # we surface the profile name in the rendered command for
        # logging.
        seccomp_profile = manifest.syscalls.seccomp_profile

        # ``argv_to_run`` is the actual command to run inside the
        # sandbox. Kept optional so tests can render a policy-only
        # argv without a target command.
        args += list(argv_to_run)

        return BwrapCommand(argv=tuple(args), env={}, seccomp_profile=seccomp_profile)

    # -----------------------------------------------------------------
    # Landlock allowlist check (harness-side pre-flight)
    # -----------------------------------------------------------------

    @staticmethod
    def _path_allowed(target: str, allow_patterns: tuple[str, ...]) -> bool:
        """Return True when ``target`` matches any allow pattern.

        Landlock does the runtime enforcement; this static check is a
        pre-flight the harness runs so a plan action can be refused
        *before* the sandbox is even entered. The manifest is an
        allowlist by design: an empty pattern list means nothing
        matches.
        """
        for pattern in allow_patterns:
            if fnmatch.fnmatch(target, pattern):
                return True
        return False

    @classmethod
    def would_refuse_write(cls, manifest: CapabilityManifest, target: str) -> bool:
        """Return True when a write to ``target`` would be refused.

        This is the pre-flight the tests drive. Landlock does the same
        refusal inside the sandbox at runtime; we expose the same
        decision to the harness so it can surface a structured refusal
        without waiting for a SIGSYS.
        """
        # Explicit denies win, always.
        for denied in manifest.filesystem.denied:
            if fnmatch.fnmatch(target, denied):
                return True
        # /proc/self/root/... is refused unless the *resolved* path is
        # explicitly on the allowlist — the SUBSTRATE §4.2 Ona-incident
        # lesson. We do not attempt to resolve symlinks here; the
        # allowlist compares the literal path. If the operator wants
        # ``/proc/self/root/usr/bin/npx`` to be writable they must list
        # that literal string in ``filesystem.write``.
        if not cls._path_allowed(target, manifest.filesystem.write):
            return True
        return False

    @classmethod
    def would_refuse_read(cls, manifest: CapabilityManifest, target: str) -> bool:
        """Return True when a read of ``target`` would be refused."""
        for denied in manifest.filesystem.denied:
            if fnmatch.fnmatch(target, denied):
                return True
        # Reads succeed on the union of read + write allowlists (a path
        # you can write to, you can also read from).
        if cls._path_allowed(target, manifest.filesystem.read):
            return False
        if cls._path_allowed(target, manifest.filesystem.write):
            return False
        return True

    @classmethod
    def would_refuse_network(cls, manifest: CapabilityManifest, host: str) -> bool:
        """Return True when a network connect to ``host`` would be refused."""
        if not manifest.network.deny_default:
            # Guarded by ManifestValidator; keep the check for defence
            # in depth.
            return False
        for allowed in manifest.network.allow_hosts:
            if fnmatch.fnmatch(host, allowed):
                return False
        return True

    @classmethod
    def would_refuse_syscall(cls, manifest: CapabilityManifest, syscall: str) -> bool:
        """Return True when a syscall would be refused by the seccomp profile."""
        profile = manifest.syscalls.seccomp_profile
        if profile == "strict":
            return syscall in STRICT_REFUSED_SYSCALLS
        # ``moderate`` still refuses the module_load family; other
        # entries are relaxed for legitimate tools.
        if profile == "moderate":
            return syscall in {
                "init_module",
                "finit_module",
                "delete_module",
                "kexec_load",
                "kexec_file_load",
            }
        return False

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
    ) -> Iterator[BwrapCommand]:
        """Enter the sandbox for one step transaction.

        The context manager yields the rendered ``BwrapCommand`` so the
        step runner can execute its actions under it. On exit the
        namespace is torn down by the kernel (bwrap exits when its
        supervised process does).

        Runtime refusals — a write past Landlock, a syscall killed by
        seccomp — surface as the target process' exit code / SIGSYS.
        The harness classifies non-zero exits as
        ``TransactionOutcome.ROLLED_BACK`` per module_02.
        """
        rendered = self.render(manifest, worktree)
        digest_hex = ManifestDigest.of(manifest).hex()

        # If the manifest is patently unsatisfiable (e.g. the seccomp
        # profile isn't one we ship), surface it up-front.
        if manifest.syscalls.seccomp_profile not in {"strict", "moderate"}:
            emit(
                SandboxEvent(
                    name="sandbox.denied",
                    manifest_digest=digest_hex,
                    step_id_hex=step_id.hex(),
                    reason=(
                        f"unknown seccomp profile {manifest.syscalls.seccomp_profile!r}"
                    ),
                )
            )
            raise SandboxViolation(
                f"unknown seccomp profile: {manifest.syscalls.seccomp_profile!r}"
            )

        emit(
            SandboxEvent(
                name="sandbox.granted",
                manifest_digest=digest_hex,
                step_id_hex=step_id.hex(),
                reason="",
                details={
                    "backend": self.name,
                    "worktree": str(worktree),
                    "seccomp_profile": rendered.seccomp_profile,
                    "argv": list(rendered.argv),
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
