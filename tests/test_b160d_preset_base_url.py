"""B-160d: RACT_PRESET_BASE_URL points a preset at a fake server; key pairing never follows it."""

from __future__ import annotations

from pathlib import Path

import yaml

from ract import env_registry
from ract.provider_presets import PRESETS, get_preset
from ract.providers.openai_provider import OpenAICompatibleProvider, key_hosts
from ract.setup import wizard
from tests.setup.test_wizard import SERVER, _git_init, _io

FAKE = "http://127.0.0.1:18099/v1"
THROWAWAY = "sk-throwaway-b160d-0000000000000000"


def test_the_override_replaces_only_the_named_preset(monkeypatch) -> None:
    monkeypatch.setenv("RACT_PRESET_BASE_URL", f"openrouter={FAKE}/")
    assert get_preset("openrouter")["providers"]["openrouter"]["url"] == FAKE
    assert (
        get_preset("openai")["providers"]["openai"]["url"]
        == PRESETS["openai"]["providers"]["openai"]["url"]
    )
    assert PRESETS["openrouter"]["providers"]["openrouter"]["url"] != FAKE


def test_an_override_that_is_not_an_address_is_ignored(monkeypatch) -> None:
    monkeypatch.setenv("RACT_PRESET_BASE_URL", "openrouter=file:///etc/passwd")
    assert (
        get_preset("openrouter")["providers"]["openrouter"]["url"]
        == PRESETS["openrouter"]["providers"]["openrouter"]["url"]
    )


def test_the_override_never_pairs_a_key_with_its_host(monkeypatch) -> None:
    before = key_hosts("OPENROUTER_API_KEY")
    monkeypatch.setenv(
        "RACT_PRESET_BASE_URL", "openrouter=https://elsewhere.example/v1"
    )
    assert key_hosts("OPENROUTER_API_KEY") == before
    assert "elsewhere.example" not in key_hosts("OPENROUTER_API_KEY")


def test_a_key_is_withheld_from_an_overridden_host_the_operator_did_not_pair(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "RACT_PRESET_BASE_URL", "openrouter=https://elsewhere.example/v1"
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", THROWAWAY)
    monkeypatch.delenv("RACT_KEY_HOSTS", raising=False)
    spec = get_preset("openrouter")["providers"]["openrouter"]
    provider = OpenAICompatibleProvider(spec)
    assert provider.api_key == "no-key" and provider._env_key_withheld


def test_setup_writes_the_override_and_never_the_key(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RACT_PRESET_BASE_URL", f"openrouter={FAKE}")
    _git_init(tmp_path)
    names = sorted(wizard._ENV_VARS)
    io, said, asked = _io(
        ["", "c", str(names.index("openrouter") + 1)],
        [SERVER],
        environ={"OPENROUTER_API_KEY": THROWAWAY},
    )
    io.detect = lambda extra: []

    assert wizard.run(tmp_path, interactive=True, io=io) == 0

    config = yaml.safe_load((tmp_path / "ract.yaml").read_text(encoding="utf-8"))
    assert config["providers"]["openrouter"]["url"] == FAKE
    assert "ok: the model answered" in "\n".join(said)
    every_file = "".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in tmp_path.rglob("*")
        if p.is_file() and ".git" not in p.parts
    )
    assert THROWAWAY not in every_file and THROWAWAY not in "\n".join(said + asked)


def test_the_override_is_a_registered_security_variable() -> None:
    var = env_registry.BY_NAME["RACT_PRESET_BASE_URL"]
    assert var.cls == "security" and "tests and walks only" in var.consumer
