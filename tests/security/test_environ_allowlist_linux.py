"""Linux enforced-sandbox env allowlist wiring -- v0.5.1 wiring module_04.

Locks Lens C C-02 closure: the Linux bwrap backend must apply the
``NEVER_PASSTHROUGH`` deny surface + emit a first-class
``sandbox.env_scrubbed`` event on every ``enter``.

The Lens C audit showed that ``src/ract/security/sandbox_linux.py``
was reading ``manifest.env.passthrough`` directly and emitting
``--setenv-if-set NAME`` for each entry -- with zero consultation of
``NEVER_PASSTHROUGH``. A compromised or attacker-authored manifest
could smuggle ``OPENAI_API_KEY`` (or any credential-shape name)
directly into the sandbox. The wiring module closes that gap by
routing every passthrough through ``build_sandbox_env`` before
emitting bwrap args, AND by pre-scrubbing bwrap's parent env so
even a bug in the argv iteration cannot regress the defense.

Reference:
- ``_BUILD/audit_2026-08-21/lens_C_substrate_sandbox.md`` C-02.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_04.md``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.security.manifest import CapabilityManifest
from ract.security.sandbox import SandboxEvent, set_event_sink
from ract.security.sandbox_linux import BwrapCommand, LinuxSandbox


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def linux_backend() -> LinuxSandbox:
    """Return a LinuxSandbox with a synthetic bwrap path.

    ``bwrap_path`` is a non-empty string so the constructor's
    platform check is bypassed on non-Linux CI. The tests drive
    ``render()`` (pure Python) rather than ``enter()`` (spawns bwrap)
    so no real bwrap is needed.
    """
    return LinuxSandbox(bwrap_path="/usr/bin/bwrap")


@pytest.fixture
def event_sink():
    """Capture SandboxEvents into an in-process list.

    Resets to the default sink on teardown so leakage between tests
    is impossible.
    """
    events: list[SandboxEvent] = []
    set_event_sink(events.append)
    yield events
    from ract.security.sandbox import _default_sink

    set_event_sink(_default_sink)


# ---------------------------------------------------------------------------
# render() — pre-scrub credential-shape names
# ---------------------------------------------------------------------------


def test_render_strips_openai_api_key_from_bwrap_setenv(
    linux_backend: LinuxSandbox, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest declaring OPENAI_API_KEY must NOT reach --setenv-if-set."""
    # Seed the parent env with the credential a compromised manifest
    # would otherwise smuggle in.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-leak-if-broken")
    monkeypatch.setenv("PATH", "/usr/bin")

    manifest = CapabilityManifest(
        run_id="lin-001",
        env={"passthrough": ["OPENAI_API_KEY", "PATH"]},
    )
    rendered = linux_backend.render(manifest, tmp_path)
    assert isinstance(rendered, BwrapCommand)
    # PATH survives (DEFAULT_ALLOWLIST + explicit); OPENAI_API_KEY does not.
    assert "OPENAI_API_KEY" not in rendered.env, (
        "OPENAI_API_KEY leaked past NEVER_PASSTHROUGH into bwrap parent env"
    )
    # --setenv-if-set NAME must not name OPENAI_API_KEY either.
    argv_str = " ".join(rendered.argv)
    assert "OPENAI_API_KEY" not in argv_str, (
        "OPENAI_API_KEY appears in bwrap argv -- Lens C C-02 regression"
    )
    assert "--setenv-if-set PATH" in argv_str


def test_render_strips_aws_credentials(
    linux_backend: LinuxSandbox, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AWS_ACCESS_KEY_ID and family blocked by NEVER_PASSTHROUGH."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("PATH", "/usr/bin")

    manifest = CapabilityManifest(
        run_id="lin-002",
        env={
            "passthrough": [
                "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY",
                "PATH",
            ]
        },
    )
    rendered = linux_backend.render(manifest, tmp_path)
    assert "AWS_ACCESS_KEY_ID" not in rendered.env
    assert "AWS_SECRET_ACCESS_KEY" not in rendered.env
    argv_str = " ".join(rendered.argv)
    assert "AWS_ACCESS_KEY_ID" not in argv_str
    assert "AWS_SECRET_ACCESS_KEY" not in argv_str


def test_render_carries_env_result_audit(
    linux_backend: LinuxSandbox, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BwrapCommand.env_result carries the scrubbed/denied counters."""
    monkeypatch.setenv("SECRET_TOKEN", "sk-x")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-y")
    monkeypatch.setenv("PATH", "/usr/bin")

    manifest = CapabilityManifest(
        run_id="lin-003",
        env={"passthrough": ["OPENAI_API_KEY", "PATH"]},
    )
    rendered = linux_backend.render(manifest, tmp_path)
    assert rendered.env_result is not None
    # OPENAI_API_KEY declared -> denied.
    assert rendered.env_result.never_passthrough_denied >= 1
    # SECRET_TOKEN never declared -> scrubbed from process env (count-only).
    assert rendered.env_result.scrubbed_count >= 1


# ---------------------------------------------------------------------------
# enter() — emits sandbox.env_scrubbed on every entry
# ---------------------------------------------------------------------------


def test_enter_emits_sandbox_env_scrubbed_event(
    linux_backend: LinuxSandbox,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_sink,
) -> None:
    """Every enter() emits sandbox.env_scrubbed with backend + audit."""
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-y")

    manifest = CapabilityManifest(
        run_id="lin-004",
        env={"passthrough": ["OPENAI_API_KEY"]},
    )
    with linux_backend.enter(manifest, tmp_path, step_id=b"\x11" * 16):
        pass

    names = [e.name for e in event_sink]
    assert "sandbox.granted" in names
    assert "sandbox.env_scrubbed" in names, (
        "wiring module_04 requires sandbox.env_scrubbed on Linux enter()"
    )
    scrubbed = next(e for e in event_sink if e.name == "sandbox.env_scrubbed")
    assert scrubbed.details["backend"] == "linux-bwrap"
    assert scrubbed.details["allowlist_source"] in {"manifest", "file", "default"}
    assert "scrubbed_count" in scrubbed.details
    assert scrubbed.details["never_passthrough_denied"] >= 1


# ---------------------------------------------------------------------------
# Regression: existing manifest declaring only benign names still works
# ---------------------------------------------------------------------------


def test_render_benign_passthrough_still_works(
    linux_backend: LinuxSandbox, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest that only declares benign names sees zero denials."""
    monkeypatch.setenv("MY_BUILD_ID", "42")
    monkeypatch.setenv("PATH", "/usr/bin")

    manifest = CapabilityManifest(
        run_id="lin-005",
        env={"passthrough": ["MY_BUILD_ID", "PATH"]},
    )
    rendered = linux_backend.render(manifest, tmp_path)
    assert rendered.env.get("MY_BUILD_ID") == "42"
    assert rendered.env.get("PATH") == "/usr/bin"
    argv_str = " ".join(rendered.argv)
    assert "--setenv-if-set MY_BUILD_ID" in argv_str
    assert "--setenv-if-set PATH" in argv_str
    assert rendered.env_result is not None
    assert rendered.env_result.never_passthrough_denied == 0


# RACT 0.5.1
