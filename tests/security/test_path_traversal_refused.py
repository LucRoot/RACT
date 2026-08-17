"""SUBSTRATE §4.2: path traversal refused at the sandbox layer, not Python-level.

The manifest is an allowlist. A write to ``../../etc/passwd`` is refused
because the resolved target is not on ``filesystem.write``; the refusal
is a policy fact, not a lexical check on ``..``.
"""

from __future__ import annotations

import sys

import pytest

from ract.security.manifest import (
    CapabilityManifest,
    FilesystemPolicy,
)


@pytest.fixture
def sandbox_cls():
    """Pick the platform-appropriate backend class for pre-flight checks.

    Linux → LinuxSandbox; macOS → MacosSandbox; Windows → skip
    (kernel primitives unavailable). The pre-flight ``would_refuse_*``
    classmethods do not shell out, so they work everywhere except where
    the module refuses to import on the wrong OS — which is fine because
    both modules import cleanly on all platforms per module design.
    """
    if sys.platform.startswith("linux"):
        from ract.security.sandbox_linux import LinuxSandbox

        return LinuxSandbox
    if sys.platform == "darwin":
        from ract.security.sandbox_macos import MacosSandbox

        return MacosSandbox
    pytest.skip(
        "path-traversal refusal is enforced by Landlock (Linux) or Seatbelt "
        "(macOS); Windows has no shipped OS-enforced sandbox in this "
        "module — see the lateral chain branch A honest gap."
    )


def test_path_traversal_write_refused(sandbox_cls):
    """Writing outside the allowlisted workspace is refused."""
    manifest = CapabilityManifest(
        run_id="traversal",
        filesystem=FilesystemPolicy(write=("/workspace/*",)),
    )
    assert sandbox_cls.would_refuse_write(manifest, "/etc/passwd")
    assert sandbox_cls.would_refuse_write(manifest, "/workspace/../../etc/passwd")


def test_path_traversal_read_refused(sandbox_cls):
    """Reading outside the allowlisted read set is refused."""
    manifest = CapabilityManifest(
        run_id="traversal",
        filesystem=FilesystemPolicy(read=("/workspace/*",)),
    )
    assert sandbox_cls.would_refuse_read(manifest, "/etc/shadow")


def test_denied_wins_over_write(sandbox_cls):
    """A path in filesystem.denied is refused even if filesystem.write would allow it."""
    manifest = CapabilityManifest(
        run_id="denied-wins",
        filesystem=FilesystemPolicy(
            write=("/workspace/*",),
            denied=("/workspace/secrets",),
        ),
    )
    assert sandbox_cls.would_refuse_write(manifest, "/workspace/secrets")


# RACT 0.4.0
