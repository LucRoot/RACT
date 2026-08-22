"""End-to-end: seeded credentials do NOT reach the sandbox env.

v0.5.1 wiring module_04 integration test. Locks Lens C C-02
closure by driving the full ``resolve_backend`` -> render -> enter
path with a manifest that DECLARES a NEVER_PASSTHROUGH-family name.
The test asserts that:

1. The credential value never lands in the sandbox env dict.
2. The credential name never lands in the rendered sandbox argv
   / profile (a leaked NAME still discloses which secrets the
   operator has configured).
3. The ``sandbox.env_scrubbed`` trace event fires with a non-zero
   ``never_passthrough_denied`` counter -- the operator's audit
   surface catches the refusal.

The Linux + macOS backends can be exercised in ``render()`` mode on
any CI platform (bwrap / sandbox-exec are only spawned in ``enter``;
render is pure Python). The Windows stub is exercised via
``resolve_backend(platform_override="Windows", allow_unenforced=True)``.

Reference:
- ``_BUILD/audit_2026-08-21/lens_C_substrate_sandbox.md`` C-02.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_04.md``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.security.manifest import CapabilityManifest
from ract.security.sandbox import SandboxEvent, resolve_backend, set_event_sink
from ract.security.sandbox_linux import LinuxSandbox
from ract.security.sandbox_macos import MacosSandbox


_SEEDED_CREDENTIAL_VALUE = "sk-ract-integration-DO-NOT-LEAK"


@pytest.fixture
def seeded_env(monkeypatch: pytest.MonkeyPatch):
    """Seed the process env with fake credentials + a benign name."""
    monkeypatch.setenv("OPENAI_API_KEY", _SEEDED_CREDENTIAL_VALUE)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA-integration-fake")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("MY_BUILD_ID", "42")


@pytest.fixture
def event_sink():
    events: list[SandboxEvent] = []
    set_event_sink(events.append)
    yield events
    from ract.security.sandbox import _default_sink

    set_event_sink(_default_sink)


@pytest.fixture
def leaky_manifest() -> CapabilityManifest:
    """A manifest that DECLARES OPENAI_API_KEY -- the attack shape."""
    return CapabilityManifest(
        run_id="leak-test-001",
        env={
            "passthrough": [
                "OPENAI_API_KEY",  # NEVER_PASSTHROUGH name declared
                "AWS_ACCESS_KEY_ID",  # NEVER_PASSTHROUGH name declared
                "PATH",  # benign, should survive
                "MY_BUILD_ID",  # benign, should survive
            ]
        },
    )


# ---------------------------------------------------------------------------
# Linux enforced backend
# ---------------------------------------------------------------------------


def test_linux_backend_refuses_credential_end_to_end(
    seeded_env,
    leaky_manifest: CapabilityManifest,
    tmp_path: Path,
    event_sink,
) -> None:
    """Linux bwrap: credentials absent from env, argv, and audit passes."""
    backend = LinuxSandbox(bwrap_path="/usr/bin/bwrap")
    with backend.enter(leaky_manifest, tmp_path, step_id=b"\x33" * 16) as rendered:
        # Property 1: credential value NEVER in the child env.
        assert _SEEDED_CREDENTIAL_VALUE not in rendered.env.values()
        assert "OPENAI_API_KEY" not in rendered.env
        assert "AWS_ACCESS_KEY_ID" not in rendered.env
        # Benign names survive.
        assert rendered.env.get("PATH") == "/usr/bin:/bin"
        assert rendered.env.get("MY_BUILD_ID") == "42"
        # Property 2: credential NAME never in argv.
        argv_str = " ".join(rendered.argv)
        assert "OPENAI_API_KEY" not in argv_str
        assert "AWS_ACCESS_KEY_ID" not in argv_str
        assert _SEEDED_CREDENTIAL_VALUE not in argv_str

    # Property 3: audit event fires.
    scrubbed = [e for e in event_sink if e.name == "sandbox.env_scrubbed"]
    assert scrubbed, "no sandbox.env_scrubbed event on Linux enter()"
    assert scrubbed[0].details["never_passthrough_denied"] >= 2


# ---------------------------------------------------------------------------
# macOS enforced backend
# ---------------------------------------------------------------------------


def test_macos_backend_refuses_credential_end_to_end(
    seeded_env,
    leaky_manifest: CapabilityManifest,
    tmp_path: Path,
    event_sink,
) -> None:
    """macOS Seatbelt: credentials absent from env + audit passes."""
    backend = MacosSandbox(sandbox_exec_path="/usr/bin/sandbox-exec")
    with backend.enter(leaky_manifest, tmp_path, step_id=b"\x44" * 16) as rendered:
        assert _SEEDED_CREDENTIAL_VALUE not in rendered.env.values()
        assert "OPENAI_API_KEY" not in rendered.env
        assert "AWS_ACCESS_KEY_ID" not in rendered.env
        assert rendered.env.get("PATH") == "/usr/bin:/bin"

    scrubbed = [e for e in event_sink if e.name == "sandbox.env_scrubbed"]
    assert scrubbed, "no sandbox.env_scrubbed event on macOS enter()"
    assert scrubbed[0].details["never_passthrough_denied"] >= 2


# ---------------------------------------------------------------------------
# Windows unenforced stub
# ---------------------------------------------------------------------------


def test_windows_stub_emits_env_scrubbed_end_to_end(
    seeded_env,
    leaky_manifest: CapabilityManifest,
    tmp_path: Path,
    event_sink,
) -> None:
    """Windows stub: same audit event fires on the fallback path."""
    backend = resolve_backend(platform_override="Windows", allow_unenforced=True)
    with backend.enter(leaky_manifest, tmp_path, step_id=b"\x55" * 16):
        pass

    scrubbed = [e for e in event_sink if e.name == "sandbox.env_scrubbed"]
    assert scrubbed, "wiring module_04: Windows stub must emit sandbox.env_scrubbed"
    assert scrubbed[0].details["backend"] == "stub"
    assert scrubbed[0].details["never_passthrough_denied"] >= 2


# ---------------------------------------------------------------------------
# Audit surface parity across backends
# ---------------------------------------------------------------------------


def test_all_three_backends_emit_identical_env_scrubbed_payload_shape(
    seeded_env,
    leaky_manifest: CapabilityManifest,
    tmp_path: Path,
) -> None:
    """Payload keys are identical across Linux, macOS, and Windows stub.

    An auditor running ``grep sandbox.env_scrubbed`` across a run's
    trace log expects the same shape regardless of which backend
    happened to fire. This test asserts payload-key parity so a
    downstream reporter can rely on a stable schema.
    """
    events_by_backend: dict[str, SandboxEvent] = {}

    for backend, backend_name in (
        (LinuxSandbox(bwrap_path="/usr/bin/bwrap"), "linux-bwrap"),
        (MacosSandbox(sandbox_exec_path="/usr/bin/sandbox-exec"), "macos-sandbox-exec"),
        (
            resolve_backend(platform_override="Windows", allow_unenforced=True),
            "stub",
        ),
    ):
        events: list[SandboxEvent] = []
        set_event_sink(events.append)
        try:
            with backend.enter(leaky_manifest, tmp_path, step_id=b"\x66" * 16):
                pass
        finally:
            from ract.security.sandbox import _default_sink

            set_event_sink(_default_sink)
        env_scrubbed = [e for e in events if e.name == "sandbox.env_scrubbed"]
        assert env_scrubbed, f"no sandbox.env_scrubbed from {backend_name}"
        events_by_backend[backend_name] = env_scrubbed[0]

    expected_keys = {
        "backend",
        "allowlist_source",
        "scrubbed_count",
        "never_passthrough_denied",
        # v0.5.1 wiring module_04 SP Q6 amendment: heuristic
        # credential-shape detector count -- non-zero flags a new
        # credential family the deny surface does not yet recognise.
        "credential_shaped_unblocked_count",
        # v0.5.2 module_02 (DA-A F-3 close): per-family bucket counts
        # for the denied allowlist entries.
        "refused_family_counts",
    }
    for backend_name, event in events_by_backend.items():
        assert set(event.details.keys()) == expected_keys, (
            f"{backend_name} sandbox.env_scrubbed payload key drift; "
            f"expected {sorted(expected_keys)}, got {sorted(event.details.keys())}"
        )
        assert event.details["backend"] == backend_name
        assert event.details["allowlist_source"] in {"manifest", "file", "default"}


# RACT 0.5.1
