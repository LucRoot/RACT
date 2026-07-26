"""SUBSTRATE §4.2 April-2026 Ona incident regression.

The Bubblewrap escape used ``/proc/self/root/usr/bin/npx`` — a resolved
path that landed on a denied binary because the denylist enumerated
origins, not resolved paths. An allowlist inverts the burden: the
sandbox refuses unless the *literal resolved path* is on the allowlist.

The test is named ``test_ona_2026_04`` in code so it stays a first-class
regression.
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
    if sys.platform.startswith("linux"):
        from ract.security.sandbox_linux import LinuxSandbox

        return LinuxSandbox
    if sys.platform == "darwin":
        from ract.security.sandbox_macos import MacosSandbox

        return MacosSandbox
    pytest.skip(
        "OS-enforced filesystem allowlist is unavailable on this platform "
        "(lateral chain branch A). The manifest still refuses the synonym "
        "at author time via ManifestValidator; the kernel-layer refusal "
        "tested here is Linux/macOS only."
    )


def test_ona_2026_04(sandbox_cls):
    """A denied binary reached via ``/proc/self/root/`` is still refused."""
    manifest = CapabilityManifest(
        run_id="ona-regression",
        filesystem=FilesystemPolicy(
            # Operator wanted to allow ``/workspace/*`` writes only.
            write=("/workspace/*",),
            # Operator wanted to deny ``npx`` execution — the manifest
            # names the literal target the runtime would need to invoke.
            denied=("/usr/bin/npx", "/proc/self/root/usr/bin/npx"),
        ),
    )
    # The direct path is refused.
    assert sandbox_cls.would_refuse_write(manifest, "/usr/bin/npx")
    # The ``/proc/self/root/`` synonym is refused — this is the
    # allowlist-vs-denylist lesson: even if we forgot to list the
    # synonym in ``denied``, the allowlist would still refuse it because
    # it is not on ``filesystem.write``. But listing it explicitly in
    # ``denied`` makes the refusal loud and named.
    assert sandbox_cls.would_refuse_write(manifest, "/proc/self/root/usr/bin/npx")


def test_ona_synonym_refused_even_without_explicit_deny(sandbox_cls):
    """Allowlist alone is enough: an unnamed synonym is refused."""
    manifest = CapabilityManifest(
        run_id="ona-allowlist-only",
        filesystem=FilesystemPolicy(write=("/workspace/*",)),
    )
    assert sandbox_cls.would_refuse_write(manifest, "/proc/self/root/usr/bin/npx")


# RACT 0.4.0
