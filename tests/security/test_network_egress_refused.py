"""Network egress refused unless the host is on ``manifest.network.allow_hosts``.

The kernel/BSD-layer refusal (routing packet through a proxy or the
namespace's ``--unshare-net`` flag) happens at runtime; the harness-side
pre-flight the tests drive here matches the same allowlist logic so
plan-time refusal is possible without waiting for a network attempt.
"""

from __future__ import annotations

import sys

import pytest

from ract.security.manifest import (
    CapabilityManifest,
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
        "runtime network refusal is enforced by the Linux namespace / "
        "Seatbelt policy; Windows has no shipped enforcement — the "
        "allow-unenforced-sandbox flag records this loudly."
    )


def test_deny_default_refuses_unlisted_host(sandbox_cls):
    manifest = CapabilityManifest(
        run_id="net",
        network=NetworkPolicy(allow_hosts=("example.com",)),
    )
    assert sandbox_cls.would_refuse_network(manifest, "evil.example.net")
    assert not sandbox_cls.would_refuse_network(manifest, "example.com")


def test_allow_host_glob(sandbox_cls):
    manifest = CapabilityManifest(
        run_id="net-glob",
        network=NetworkPolicy(allow_hosts=("*.example.com",)),
    )
    assert not sandbox_cls.would_refuse_network(manifest, "api.example.com")
    assert sandbox_cls.would_refuse_network(manifest, "example.org")


# RACT 0.4.0
