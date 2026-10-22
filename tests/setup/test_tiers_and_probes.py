"""B-015: machine probe, local server detection, model guidance."""

from __future__ import annotations

import datetime
from typing import Any

import pytest

from ract.setup import host_probe, local_probe, tiers


# ----------------------------------------------------------------- tiers (C)


@pytest.mark.parametrize(
    ("total_gb", "expected"),
    [
        (4, "qwen2.5-coder-1.5b"),  # 2.4 GB dedicated: below every entry
        (8, "qwen2.5-coder-3b"),
        (16, "qwen2.5-coder-7b"),
        (32, "qwen2.5-coder-14b"),
        (64, "qwen2.5-coder-32b"),
    ],
)
def test_the_default_share_of_memory_picks_a_tier(total_gb: int, expected: str) -> None:
    dedicated = tiers.default_dedicated_gb(total_gb)
    assert tiers.recommend(dedicated).tier.id == expected


def test_too_little_memory_says_so() -> None:
    advice = tiers.recommend(2.0)
    assert advice.tier.id == "qwen2.5-coder-1.5b"
    assert "less than the smallest model needs" in advice.reason


def test_unknown_memory_picks_the_smallest_and_says_why() -> None:
    advice = tiers.recommend(None)
    assert advice.tier.id == "qwen2.5-coder-1.5b"
    assert "could not be read" in advice.reason


def test_the_table_is_dated_guidance_with_install_text() -> None:
    reviewed, table = tiers.load()
    datetime.date.fromisoformat(reviewed)
    assert [t.needs_gb for t in table] == sorted(t.needs_gb for t in table)
    for tier in table:
        assert tier.weights_gb < tier.needs_gb
        steps = "\n".join(tiers.install_steps(tier))
        assert "LM Studio" in steps and "llama.cpp" in steps
        assert "curl" not in steps and "wget" not in steps  # setup never downloads


# ---------------------------------------------------------- host probe (A)


def test_the_host_probe_reads_or_says_unknown() -> None:
    profile = host_probe.probe_host()
    assert profile.python_version.count(".") == 2
    assert profile.total_ram_bytes is None or profile.total_ram_bytes > 2**28
    if profile.total_ram_bytes and profile.available_ram_bytes:
        assert profile.available_ram_bytes <= profile.total_ram_bytes
    lines = host_probe.describe(profile)
    assert any(line.startswith("memory: ") for line in lines)


def test_unknown_memory_is_described_as_unknown() -> None:
    profile = host_probe.HostProfile(
        "Linux", "x86_64", "3.11.9", None, None, None, None, None, None
    )
    text = "\n".join(host_probe.describe(profile))
    assert "memory: unknown total, unknown available" in text
    assert "git: not found" in text


# ---------------------------------------------------------- detection (B)


def test_only_the_default_addresses_and_named_ones_are_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RACT_BASE_URL", "http://10.0.0.5:9999/v1/")
    asked: list[str] = []
    monkeypatch.setattr(local_probe, "_ask", lambda label, url: asked.append(url))

    assert local_probe.detect() == []

    assert sorted(asked) == sorted(
        [
            "http://10.0.0.5:9999/v1",
            "http://127.0.0.1:8080/v1",
            "http://127.0.0.1:11434/v1",
            "http://127.0.0.1:1234/v1",
            "http://127.0.0.1:8000/v1",
        ]
    )  # never a range of ports


def test_a_server_on_a_default_address_is_found(
    fake_model_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = fake_model_server("baseline_j4_today")
    monkeypatch.setattr(
        local_probe, "DEFAULT_SERVERS", (("llama.cpp server", server.base_url),)
    )

    [found] = local_probe.detect()

    assert found.label == "llama.cpp server"
    assert found.url == server.base_url
    assert found.models  # what the server reports about itself


def test_a_custom_address_from_the_environment_is_found(
    fake_model_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = fake_model_server("baseline_j4_today")
    monkeypatch.setattr(local_probe, "DEFAULT_SERVERS", ())
    monkeypatch.setenv("RACT_BASE_URL", server.base_url)

    [found] = local_probe.detect()

    assert found.label == "from RACT_BASE_URL"


def test_a_closed_port_is_not_offered(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(
        local_probe, "DEFAULT_SERVERS", (("x", f"http://127.0.0.1:{port}/v1"),)
    )

    assert local_probe.detect() == []


def test_probes_send_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    # G-056: a probe must not be a way around S-025's key-to-host binding.
    import httpx

    from ract import egress_ledger

    sentinel = "sk-test-" + "Z" * 40
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    monkeypatch.setenv("RACT_BASE_URL", "http://10.9.9.9:7777/v1")
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.headers))
        return httpx.Response(200, json={"data": [{"id": "m"}]})

    real = egress_ledger.client

    def client(kind: str, **kwargs: Any) -> httpx.Client:
        assert kwargs.get("trust_env") is False
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(kind, **kwargs)

    monkeypatch.setattr(local_probe.egress_ledger, "client", client)

    found = local_probe.detect()

    assert len(found) == len(seen) == 5
    for headers in seen:
        assert "authorization" not in {k.lower() for k in headers}
        assert sentinel not in " ".join(headers.values())
