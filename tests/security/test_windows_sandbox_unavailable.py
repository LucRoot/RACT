"""Windows honest-gap surface (lateral chain branch A).

On Windows, ``resolve_backend`` refuses to return a backend unless the
operator sets ``allow_unenforced=True``. The flag is loud (event
``sandbox.unenforced`` fires on every step entry) and the run report
stamps it. This test runs on every platform by driving
``platform_override``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.security.manifest import CapabilityManifest
from ract.security.sandbox import (
    SandboxEvent,
    SandboxNotAvailable,
    UnenforcedSandbox,
    resolve_backend,
    set_event_sink,
)


def test_windows_refuses_without_escape_hatch():
    with pytest.raises(SandboxNotAvailable) as excinfo:
        resolve_backend(platform_override="Windows")
    assert "--allow-unenforced-sandbox" in str(excinfo.value)


def test_windows_returns_stub_with_escape_hatch(tmp_path: Path):
    backend = resolve_backend(platform_override="Windows", allow_unenforced=True)
    assert isinstance(backend, UnenforcedSandbox)
    assert backend.enforced is False
    assert backend.name == "stub"

    events: list[SandboxEvent] = []
    set_event_sink(events.append)
    try:
        manifest = CapabilityManifest(run_id="win-run")
        with backend.enter(manifest, tmp_path, step_id=b"\x00" * 16):
            pass
    finally:
        # Reset the sink so no other test sees these events. module_05
        # renamed the module-level default to _default_sink because it
        # now forwards to the trace event log rather than dropping.
        from ract.security.sandbox import _default_sink

        set_event_sink(_default_sink)

    # v0.5.1 module_05: UnenforcedSandbox emits BOTH the classic
    # ``sandbox.unenforced`` event AND a ``sandbox.granted`` event
    # carrying the env-allowlist audit (D1 defense: env scrubbing
    # applies even on the unenforced stub). The unenforced event
    # remains index 0; the granted-with-env-audit event lands next.
    assert len(events) == 2
    assert events[0].name == "sandbox.unenforced"
    assert "unenforced-sandbox" in events[0].reason
    assert events[0].step_id_hex == ("00" * 16)
    assert events[1].name == "sandbox.granted"
    assert events[1].reason == "env_allowlist_computed"
    assert "env_scrubbed_count" in events[1].details
    assert events[1].details["env_never_passthrough_denied"] >= 0


def test_unknown_platform_also_refuses():
    with pytest.raises(SandboxNotAvailable):
        resolve_backend(platform_override="Plan9")


# RACT 0.4.0
