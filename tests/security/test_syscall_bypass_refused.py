"""Under the ``strict`` seccomp profile, ``ptrace`` / ``mount`` / ``unshare``
are refused with SIGSYS.

Lateral chain branch E: CI runners without kernel support for seccomp
skip this test with a specific reason. The pre-flight refusal test is
Linux-only because the enforcement primitive is Linux-only (macOS has no
seccomp equivalent).
"""

from __future__ import annotations

import sys

import pytest

from ract.security.manifest import (
    CapabilityManifest,
    SyscallPolicy,
)


@pytest.fixture
def linux_sandbox_cls():
    if not sys.platform.startswith("linux"):
        pytest.skip(
            "seccomp-bpf is Linux-only; macOS and Windows have no equivalent "
            "kernel primitive. On macOS the sandbox uses Seatbelt for "
            "filesystem/network only; on Windows the sandbox is unenforced "
            "and the run report stamps --allow-unenforced-sandbox."
        )
    try:
        from ract.security.sandbox_linux import LinuxSandbox

        return LinuxSandbox
    except ImportError:  # pragma: no cover — module always imports on Linux
        pytest.skip("LinuxSandbox module unavailable on this runner")


def test_strict_profile_refuses_ptrace(linux_sandbox_cls):
    manifest = CapabilityManifest(
        run_id="syscall",
        syscalls=SyscallPolicy(seccomp_profile="strict"),
    )
    assert linux_sandbox_cls.would_refuse_syscall(manifest, "ptrace")
    assert linux_sandbox_cls.would_refuse_syscall(manifest, "mount")
    assert linux_sandbox_cls.would_refuse_syscall(manifest, "unshare")
    assert linux_sandbox_cls.would_refuse_syscall(manifest, "init_module")


def test_moderate_profile_relaxes_ptrace(linux_sandbox_cls):
    manifest = CapabilityManifest(
        run_id="syscall-mod",
        syscalls=SyscallPolicy(seccomp_profile="moderate"),
    )
    # moderate lets some things through but never module-loading.
    assert not linux_sandbox_cls.would_refuse_syscall(manifest, "ptrace")
    assert linux_sandbox_cls.would_refuse_syscall(manifest, "init_module")


# RACT 0.4.0
