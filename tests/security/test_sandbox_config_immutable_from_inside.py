"""The sandbox configuration is not mutable by the sandboxed process.

The kernel-side guarantee (Landlock rules cannot be relaxed once
loaded; seccomp filters survive execve when applied with TSYNC) is
enforced by the Linux kernel documentation cited in
``sandbox_linux.py``. Here we assert the harness-side surface: the
manifest is not passed *into* the sandbox as a file, and the rendered
bwrap command does not bind-mount the manifest source into /workspace.
"""

from __future__ import annotations

import sys

import pytest

from ract.security.manifest import (
    CapabilityManifest,
    FilesystemPolicy,
)


@pytest.fixture
def linux_sandbox():
    if not sys.platform.startswith("linux"):
        pytest.skip(
            "the bwrap argv rendered here is Linux-specific; equivalent "
            "immutability on macOS is enforced by the fact that the "
            "Seatbelt profile is passed as a `-p` argument and not "
            "bind-mounted into the sandbox."
        )
    from ract.security.sandbox_linux import LinuxSandbox

    return LinuxSandbox(bwrap_path="/nonexistent-test-bwrap")


def test_manifest_source_not_bound_into_sandbox(tmp_path, linux_sandbox):
    """The rendered bwrap command must not bind-mount the manifest source."""
    manifest = CapabilityManifest(
        run_id="immut",
        filesystem=FilesystemPolicy(write=("/workspace/*",)),
    )
    rendered = linux_sandbox.render(manifest, tmp_path)
    joined = " ".join(rendered.argv)
    # If the manifest source were bind-mounted, its bytes would surface
    # somewhere in the argv. The manifest.run_id is the smallest unique
    # marker we can grep for; asserting its absence is a proxy for the
    # invariant.
    assert manifest.run_id not in joined
    # And the render must not include any `--bind` or `--ro-bind*` that
    # references a manifest-config path outside the explicit allowlist
    # (all binds must be either the worktree, a `filesystem.read`, or a
    # `filesystem.write` entry). Since neither read nor write name
    # arbitrary config paths, only `/workspace` is bound RW here.
    bind_targets = [
        rendered.argv[i + 2]
        for i, tok in enumerate(rendered.argv)
        if tok in {"--bind", "--bind-try"} and i + 2 < len(rendered.argv)
    ]
    assert bind_targets == ["/workspace"]


def test_seccomp_profile_name_survives_render(tmp_path, linux_sandbox):
    """The seccomp profile is derived from the manifest at render time.

    A sandboxed process cannot re-render the command; the seccomp
    filter it inherits is whatever the outer bwrap invocation applied.
    """
    manifest = CapabilityManifest(run_id="scp")
    rendered = linux_sandbox.render(manifest, tmp_path)
    assert rendered.seccomp_profile == "strict"


# RACT 0.4.0
