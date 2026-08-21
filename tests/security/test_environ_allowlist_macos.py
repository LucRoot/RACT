"""macOS enforced-sandbox env allowlist wiring -- v0.5.1 wiring module_04.

Locks Lens C C-02 closure on the macOS Seatbelt backend. Before the
wiring pipeline, ``sandbox_macos.py`` had ZERO env scrubbing --
``sandbox-exec`` inherits whatever env the parent hands it, and the
Seatbelt profile lacks a Linux ``--clearenv`` equivalent. A manifest
with a NEVER_PASSTHROUGH-family name declared in ``env.passthrough``
would slip directly through. This test locks that gap.

Reference:
- ``_BUILD/audit_2026-08-21/lens_C_substrate_sandbox.md`` C-02.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_04.md``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.security.manifest import CapabilityManifest
from ract.security.sandbox import SandboxEvent, set_event_sink
from ract.security.sandbox_macos import MacosSandbox, SeatbeltProfile


@pytest.fixture
def macos_backend() -> MacosSandbox:
    """A MacosSandbox with a synthetic sandbox-exec path.

    The tests drive ``render()`` (pure Python) so no real
    sandbox-exec is needed; this works on every CI platform.
    """
    return MacosSandbox(sandbox_exec_path="/usr/bin/sandbox-exec")


@pytest.fixture
def event_sink():
    events: list[SandboxEvent] = []
    set_event_sink(events.append)
    yield events
    from ract.security.sandbox import _default_sink

    set_event_sink(_default_sink)


def test_render_strips_openai_api_key_from_seatbelt_env(
    macos_backend: MacosSandbox, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seatbelt profile env does NOT carry a NEVER_PASSTHROUGH name."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-leak-if-broken")
    monkeypatch.setenv("PATH", "/usr/bin")

    manifest = CapabilityManifest(
        run_id="mac-001",
        env={"passthrough": ["OPENAI_API_KEY", "PATH"]},
    )
    rendered = macos_backend.render(manifest, tmp_path)
    assert isinstance(rendered, SeatbeltProfile)
    assert "OPENAI_API_KEY" not in rendered.env, (
        "OPENAI_API_KEY leaked past NEVER_PASSTHROUGH into sandbox-exec env"
    )
    assert rendered.env.get("PATH") == "/usr/bin"


def test_render_strips_aws_credentials(
    macos_backend: MacosSandbox, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("PATH", "/usr/bin")

    manifest = CapabilityManifest(
        run_id="mac-002",
        env={
            "passthrough": [
                "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY",
                "PATH",
            ]
        },
    )
    rendered = macos_backend.render(manifest, tmp_path)
    assert "AWS_ACCESS_KEY_ID" not in rendered.env
    assert "AWS_SECRET_ACCESS_KEY" not in rendered.env


def test_render_carries_env_result_audit(
    macos_backend: MacosSandbox, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SECRET_TOKEN", "sk-x")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-y")
    monkeypatch.setenv("PATH", "/usr/bin")

    manifest = CapabilityManifest(
        run_id="mac-003",
        env={"passthrough": ["OPENAI_API_KEY", "PATH"]},
    )
    rendered = macos_backend.render(manifest, tmp_path)
    assert rendered.env_result is not None
    assert rendered.env_result.never_passthrough_denied >= 1
    assert rendered.env_result.scrubbed_count >= 1


def test_enter_emits_sandbox_env_scrubbed_event(
    macos_backend: MacosSandbox,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_sink,
) -> None:
    """Every enter() emits sandbox.env_scrubbed with backend + audit."""
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-y")

    manifest = CapabilityManifest(
        run_id="mac-004",
        env={"passthrough": ["GITHUB_TOKEN"]},
    )
    with macos_backend.enter(manifest, tmp_path, step_id=b"\x22" * 16):
        pass

    names = [e.name for e in event_sink]
    assert "sandbox.granted" in names
    assert "sandbox.env_scrubbed" in names, (
        "wiring module_04 requires sandbox.env_scrubbed on macOS enter()"
    )
    scrubbed = next(e for e in event_sink if e.name == "sandbox.env_scrubbed")
    assert scrubbed.details["backend"] == "macos-sandbox-exec"
    assert scrubbed.details["allowlist_source"] in {"manifest", "file", "default"}
    assert "scrubbed_count" in scrubbed.details
    assert scrubbed.details["never_passthrough_denied"] >= 1


# RACT 0.5.1
