"""B-059: the Advice section of ``ract doctor``.

``advise`` is pure: it takes the facts and returns plain lines. The doctor
gathers the facts. The key variable is read for its presence only, and no
value is printed, stored or compared outside this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ract.doctor import RactDoctor
from ract.doctor_advice import (
    KeyFacts,
    Memory,
    advise,
    model_size_billions,
    render,
)
from ract.providers.capability_probe import Finding, ProviderProbe

SENTINEL = "sk-SENTINEL-b059-8820"


def _probe(
    name: str = "local",
    *,
    tools: str | None = None,
    context: int | None = None,
    chat: str = "works",
) -> ProviderProbe:
    probe = ProviderProbe(name=name, url="http://127.0.0.1:8010/v1", model="m")
    probe.findings.append(
        Finding("chat", chat, "0.1 s" if chat == "works" else "refused")
    )
    probe.findings.append(Finding("streaming", "works"))
    if tools is None:
        probe.findings.append(Finding("tool calling", "works"))
    else:
        probe.findings.append(Finding("tool calling", tools, "", "fallback"))
    probe.findings.append(Finding("reasoning text", "not returned"))
    if context is None:
        probe.findings.append(
            Finding("context window", "unknown", "the server does not say")
        )
    else:
        probe.findings.append(
            Finding(
                "context window",
                "known",
                f"{context} tokens, from the server",
                "",
                context,
            )
        )
    return probe


# ---------------------------------------------------------------- 1 and 2: memory


def test_a_7b_model_on_a_16_gb_machine_with_12_gb_free_gets_no_memory_advice() -> None:
    lines = advise(
        {"providers": {"local": {"model": "qwen-7b-instruct"}}},
        Memory(total_gb=16.0, free_gb=12.0),
        [],
        [],
    )
    assert not any("parameters" in line for line in lines)


def test_a_32b_model_on_a_16_gb_machine_gets_the_numbers_and_says_estimate() -> None:
    lines = advise(
        {"providers": {"local": {"model": "x-32b"}}},
        Memory(total_gb=16.0, free_gb=12.0),
        [],
        [],
    )
    text = "\n".join(lines)
    assert "model 'x-32b' is about 32 billion parameters" in text
    assert "at 4-bit that needs roughly 21 GB" in text
    assert "16 GB total and 12 GB free right now" in text
    assert "These are estimates." in text


@pytest.mark.parametrize("model", ["gpt-4o-mini", "my-model", "a-llama-variant"])
def test_a_model_id_with_no_size_gets_no_memory_advice(model: str) -> None:
    assert model_size_billions(model) is None
    lines = advise(
        {"providers": {"local": {"model": model}}},
        Memory(total_gb=4.0, free_gb=1.0),
        [],
        [],
    )
    assert not any("parameters" in line for line in lines)


def test_no_memory_reading_means_no_memory_advice() -> None:
    lines = advise(
        {"providers": {"local": {"model": "x-70b"}}}, Memory(None, None), [], []
    )
    assert not any("parameters" in line for line in lines)


# ---------------------------------------------------------------- 3: context


def test_a_budget_above_the_server_context_names_both_numbers() -> None:
    lines = advise(
        {"context_budget_tokens": 16000, "providers": {"local": {}}},
        None,
        [_probe(context=8192)],
        [],
    )
    text = "\n".join(lines)
    assert (
        "ract.yaml asks for 16,000 tokens of context; the server reports 8,192." in text
    )
    assert "Set context_budget_tokens to 8,000 or less" in text


def test_an_unknown_server_context_gets_no_context_advice() -> None:
    lines = advise(
        {"context_budget_tokens": 16000, "providers": {"local": {}}},
        None,
        [_probe(context=None)],
        [],
    )
    assert not any("context" in line.lower() for line in lines)


# ---------------------------------------------------------------- 4: tools


def test_a_server_without_tool_calls_gets_the_fallback_line() -> None:
    lines = advise(
        {"providers": {"local": {}}}, None, [_probe(tools="not supported")], []
    )
    text = "\n".join(lines)
    assert "cannot call tools" in text
    assert "RACT will use its text fallback, which works for small steps." in text


def test_a_server_with_tool_calls_gets_no_tool_line() -> None:
    lines = advise({"providers": {"local": {}}}, None, [_probe()], [])
    assert not any("tools" in line for line in lines)


# ---------------------------------------------------------------- 5: cloud keys


def test_an_unset_key_variable_is_named_without_a_value() -> None:
    facts = [KeyFacts("cloud", "RACT_B059_UNSET", False, "api.example.invalid", False)]
    lines = advise({"providers": {"cloud": {}}}, None, [], facts)
    assert "set the environment variable RACT_B059_UNSET" in "\n".join(lines)


def test_a_set_key_whose_host_is_not_paired_names_both_and_no_value() -> None:
    facts = [KeyFacts("cloud", "RACT_B059_SET", True, "api.example.invalid", False)]
    lines = advise({"providers": {"cloud": {}}}, None, [], facts)
    text = "\n".join(lines)
    assert "RACT_B059_SET" in text and "api.example.invalid" in text
    assert SENTINEL not in text


def test_a_paired_key_reports_the_tiny_request_result() -> None:
    facts = [KeyFacts("local", "RACT_B059_SET", True, "127.0.0.1:8010", True)]
    ok = advise({"providers": {"local": {}}}, None, [_probe("local")], facts)
    assert any("key and host pair" in line and "worked" in line for line in ok)
    bad = advise(
        {"providers": {"local": {}}}, None, [_probe("local", chat="failed")], facts
    )
    assert any("tiny request failed" in line for line in bad)


# ---------------------------------------------------------------- 8: widths


def test_render_wraps_to_the_width_and_keeps_every_word() -> None:
    line = "ract.yaml asks for 16,000 tokens of context; the server reports 8,192. " * 2
    for width in (60, 80):
        rows = render([line], width)
        assert all(len(row) <= width for row in rows)
        assert " ".join(" ".join(rows).split()) == " ".join(line.split())


# ---------------------------------------------------------------- 6 and 7: the doctor


def test_no_key_value_appears_in_the_doctor_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RACT_B059_SET", SENTINEL)
    config = tmp_path / "ract.yaml"
    config.write_text(
        "project:\n  name: demo\nmanager_provider: cloud\nproviders:\n  cloud:\n"
        "    adapter: openai_compatible\n    url: https://api.example.invalid/v1\n"
        "    model: x-70b\n    api_key: ${RACT_B059_SET}\n",
        encoding="utf-8",
    )
    results = RactDoctor(config).diagnose()
    text = "\n".join(f"{r.name} {r.message}" for r in results)
    text += "\n" + "\n".join(RactDoctor(config).advice)
    assert SENTINEL not in text


def test_plain_doctor_makes_no_request_and_shows_no_live_advice(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("j1_first_run")
    config = tmp_path / "ract.yaml"
    config.write_text(
        "project:\n  name: demo\nmanager_provider: local\nproviders:\n  local:\n"
        f"    adapter: local_http\n    url: {server.base_url}\n    model: fake-coder\n",
        encoding="utf-8",
    )
    doctor = RactDoctor(config)
    doctor.diagnose()
    assert server.requests == []
    assert not any("tiny request" in line or "tools" in line for line in doctor.advice)
