"""SUBSTRATE §4.1 named incidents as first-class regression tests.

Each test constructs a plan approximating the incident (a plausible
capability-manifest that a Claude Code / Cursor / Replit-shaped agent
might have proposed the night the incident happened) and asserts the
sandbox refuses. The harness-side ``would_refuse_write`` /
``would_refuse_read`` pre-flight is the checkpoint; the kernel-layer
refusal is the same policy, enforced at a different layer.
"""

from __future__ import annotations

import sys

import pytest

from ract.security.manifest import (
    CapabilityManifest,
    FilesystemPolicy,
    NetworkPolicy,
)


@pytest.fixture
def sandbox_cls():
    if sys.platform.startswith("linux"):
        from ract.security.sandbox_linux import LinuxSandbox

        return LinuxSandbox
    if sys.platform == "darwin":
        from ract.security.sandbox_macos import MacosSandbox

        return MacosSandbox
    pytest.skip(
        "kernel-layer refusal for the named incidents is Linux/macOS "
        "only; Windows path is covered by test_windows_sandbox_unavailable."
    )


def test_incident_claude_code_home_rm_rf(sandbox_cls):
    """Claude Code ``rm -rf ~/`` incident.

    The workspace-scoped manifest allows writes only under the workspace
    root. A write to ``$HOME`` is refused because it is outside the
    allowlist. Enforcement is the OS-layer fact, not a Python string
    check on ``rm``.
    """
    manifest = CapabilityManifest(
        run_id="claude-code-home",
        filesystem=FilesystemPolicy(
            read=("/workspace/*", "/home/agent/.config/*"),
            write=("/workspace/*",),
        ),
    )
    assert sandbox_cls.would_refuse_write(manifest, "/home/agent/documents")
    assert sandbox_cls.would_refuse_write(manifest, "/home/agent/.ssh/id_rsa")


def test_incident_cursor_70_file_deletion(sandbox_cls):
    """Cursor 70-file deletion incident.

    The manifest allows writes only under a specific subdirectory of the
    workspace. A delete/write on a file outside that subdirectory is
    refused, so a "delete 70 files" plan cannot cross the boundary even
    if the plan action's textual form is innocuous.
    """
    manifest = CapabilityManifest(
        run_id="cursor-70",
        filesystem=FilesystemPolicy(
            write=("/workspace/output/*",),
            read=("/workspace/*",),
        ),
    )
    for path in [
        "/workspace/src/main.py",
        "/workspace/tests/test_main.py",
        "/workspace/README.md",
    ]:
        assert sandbox_cls.would_refuse_write(manifest, path)


def test_incident_replit_production_database_deletion(sandbox_cls):
    """Replit production-database deletion incident.

    The manifest's network allowlist has no production-database host on
    it. A connect to the production DB host is refused at the sandbox
    layer; even if the plan action classifies as tier 2 and the
    handshake registry has a stale approval, the sandbox does not read
    the handshake.
    """
    manifest = CapabilityManifest(
        run_id="replit-prod-db",
        network=NetworkPolicy(
            allow_hosts=("staging.example.com",),
            deny_default=True,
        ),
    )
    assert sandbox_cls.would_refuse_network(manifest, "prod-db.example.com")
    assert sandbox_cls.would_refuse_network(manifest, "database.production")


# RACT 0.4.0
