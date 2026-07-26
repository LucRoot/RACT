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
    backend = resolve_backend(
        platform_override="Windows", allow_unenforced=True
    )
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
        # Reset the sink so no other test sees these events.
        from ract.security.sandbox import _null_sink

        set_event_sink(_null_sink)

    assert len(events) == 1
    assert events[0].name == "sandbox.unenforced"
    assert "unenforced-sandbox" in events[0].reason
    assert events[0].step_id_hex == ("00" * 16)


def test_unknown_platform_also_refuses():
    with pytest.raises(SandboxNotAvailable):
        resolve_backend(platform_override="Plan9")


# RACT 0.4.0
