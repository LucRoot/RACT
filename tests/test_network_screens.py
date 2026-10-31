"""B-127 screens: the fetch prompt, the --no-network message, and fetched content with its
untrusted label (ADR-0048 D11 and D9). Pure text at 80, 60 and 40 columns. Fetched text is data:
it is labeled, escaped, and never printed raw.
"""

from __future__ import annotations

import pytest

from ract.ui.network_screens import (
    FETCH_CHOICES,
    UNTRUSTED_LABEL,
    FetchRequest,
    blocked_by_no_network_lines,
    fetch_prompt_lines,
    fetched_content_lines,
)

WIDTHS = (80, 60, 40)


def _flat(lines: list[str]) -> str:
    return " ".join(" ".join(lines).split())


@pytest.mark.parametrize("width", WIDTHS)
def test_the_fetch_prompt_shows_host_allowlist_cap_and_the_label(width: int) -> None:
    req = FetchRequest(
        url="https://docs.example.org/api",
        host="docs.example.org",
        allowlist_match="*.example.org",
        size_cap_kib=512,
    )
    lines = fetch_prompt_lines(req, width)
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "fetch from the web (tier 2)" in text
    assert "host: docs.example.org" in text
    assert "allowlist: matches *.example.org" in text
    assert "size cap: 512 KiB; a larger page is cut" in text
    assert "untrusted content" in text
    assert " ".join(FETCH_CHOICES.split()) in text


def test_a_host_outside_the_allowlist_says_it_will_ask() -> None:
    req = FetchRequest(
        url="https://x.test/", host="x.test", allowlist_match=None, size_cap_kib=64
    )
    assert "no entry matches this host; it will ask" in _flat(
        fetch_prompt_lines(req, 80)
    )


@pytest.mark.parametrize("width", WIDTHS)
def test_the_no_network_message_names_the_tool_and_the_way_back(width: int) -> None:
    lines = blocked_by_no_network_lines("fetch", width)
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "fetch was not run: --no-network is set" in text
    assert "remove --no-network for this run" in text


@pytest.mark.parametrize("width", WIDTHS)
def test_fetched_content_carries_the_untrusted_label_on_every_screen(
    width: int,
) -> None:
    lines = fetched_content_lines(
        "https://docs.example.org/api", "line one\nline two", width
    )
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert " ".join(UNTRUSTED_LABEL.split()) in text
    assert "from: https://docs.example.org/api" in text
    assert "| line one" in text and "| line two" in text


def test_fetched_text_with_escape_sequences_is_shown_escaped() -> None:
    lines = fetched_content_lines("https://x.test/", "ok\x1b[31m‮", 80)
    joined = "\n".join(lines)
    assert "\x1b" not in joined and "‮" not in joined
    assert "\\x1b" in joined and "\\u202e" in joined


def test_a_control_character_in_the_host_is_visible() -> None:
    req = FetchRequest(
        url="https://a.test/\x07",
        host="a.test\x1b",
        allowlist_match=None,
        size_cap_kib=1,
    )
    joined = "\n".join(fetch_prompt_lines(req, 80))
    assert "\x1b" not in joined and "\x07" not in joined
