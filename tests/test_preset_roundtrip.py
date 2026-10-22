"""B-060: every provider preset round-trips and no test reaches a real host.

Local presets are pointed at the fake model server and run one chat request
through the real provider class. Cloud presets are checked as data only: the
key field is a `${NAME}` reference and the host pairs with that name. A
guard fails any test that tries to connect to a host other than loopback.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from ract.config_check import find_config_problems
from ract.provider_presets import get_preset, list_presets
from ract.providers.openai_provider import OpenAICompatibleProvider, key_hosts

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "PROVIDER_SETUP.md"
LOCAL = {"local", "ollama", "llamacpp", "lmstudio", "vllm"}
CLOUD = {"openai", "anthropic", "zai", "moonshot", "openrouter"}


@pytest.fixture(autouse=True)
def no_real_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail a test that connects anywhere but loopback."""
    real = socket.socket.connect

    def guarded(self: socket.socket, address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else str(address)
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if not loopback:
            raise AssertionError(f"a test tried to reach a non-loopback host: {host}")
        return real(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)


def _preset_provider(name: str) -> tuple[str, dict[str, Any]]:
    config = get_preset(name)
    provider_name = config["manager_provider"]
    return provider_name, config["providers"][provider_name]


# ---------------------------------------------------------------- 1. config check


@pytest.mark.parametrize("name", list_presets())
def test_every_preset_passes_the_config_check(name: str) -> None:
    assert find_config_problems(get_preset(name)) == []


# ---------------------------------------------------------------- 2. local round trip


@pytest.mark.parametrize("name", sorted(LOCAL))
def test_a_local_preset_sends_one_chat_request_to_its_server(
    name: str, fake_model_server: Any
) -> None:
    server = fake_model_server("j1_first_run")
    provider_name, slot = _preset_provider(name)
    provider = OpenAICompatibleProvider(
        {**slot, "url": server.base_url, "max_retries": 0}
    )
    result = provider.complete([{"role": "user", "content": "hello"}])
    assert result.is_ok(), result.error
    sent = server.chat_requests[-1].body
    assert sent["model"] == slot["model"]


# ---------------------------------------------------------------- 3. cloud pairing


@pytest.mark.parametrize("name", sorted(CLOUD))
def test_a_cloud_preset_key_is_a_reference_paired_with_its_host(name: str) -> None:
    _, slot = _preset_provider(name)
    match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", slot["api_key"])
    assert match is not None, "the key must be a ${NAME} reference, never a value"
    host = urlsplit(slot["url"]).hostname
    assert host in key_hosts(match.group(1))


# ---------------------------------------------------------------- 4. init writes a file


@pytest.mark.parametrize("name", list_presets())
def test_init_provider_writes_a_file_and_refuses_to_overwrite(
    name: str, tmp_path: Path
) -> None:
    project = tmp_path / name
    project.mkdir()
    first = subprocess.run(
        [sys.executable, "-m", "ract.cli", "--init-provider", name],
        cwd=project,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    written = project / "ract.yaml"
    assert first.returncode == 0, first.stderr[-300:]
    assert written.is_file()
    for line in written.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("api_key:"):
            assert "${" in line, f"a literal key was written: {line.strip()[:20]}"
    before = written.read_bytes()
    second = subprocess.run(
        [sys.executable, "-m", "ract.cli", "--init-provider", name],
        cwd=project,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert written.read_bytes() == before, "an existing ract.yaml was overwritten"
    assert second.returncode != 0 or "exists" in (second.stdout + second.stderr).lower()


# ---------------------------------------------------------------- 5. docs table


def _doc_rows() -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    text = DOC.read_text(encoding="utf-8")
    section = text.split("## Provider presets", 1)[1]
    section = section.split("\n## ", 1)[0]
    for line in section.splitlines():
        match = re.match(r"^\|\s*`([a-z0-9_-]+)`\s*\|(.*)\|\s*$", line)
        if match:
            rows[match.group(1)] = [c.strip() for c in match.group(2).split("|")]
    return rows


def test_the_docs_table_lists_exactly_the_presets() -> None:
    assert set(_doc_rows()) == set(list_presets())


def test_every_docs_row_says_what_was_tested() -> None:
    for name, cells in _doc_rows().items():
        assert cells[-1] in {
            "tested against the fake server",
            "run against a real server",
        }, name
        if name in CLOUD:
            assert cells[-1] == "tested against the fake server"


# ---------------------------------------------------------------- 6. the guard works


def test_the_guard_refuses_a_non_loopback_connect() -> None:
    sock = socket.socket()
    try:
        with pytest.raises(AssertionError, match="non-loopback"):
            sock.connect(("203.0.113.9", 9))
    finally:
        sock.close()
