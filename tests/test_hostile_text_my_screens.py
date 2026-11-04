"""G-118: the screens the lane owns never print a raw control character from a
repository's ract.yaml or from a server's reply.

The provider probe printer and the doctor's capability row are the two places
where a server's text reaches the terminal. Each test puts an escape sequence,
a carriage return and a clear-screen code into the text and checks that none of
them is printed raw.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract import cli
from ract.doctor import RactDoctor
from ract.providers.capability_probe import Finding, ProviderProbe
from tests.test_repl import _Console

HOSTILE = "evil\x1b[2J\r" + " " * 20 + "echo ok\x1b[31m"
CONTROL = ("\x1b", "\r", "\x07")


def _probe(name: str, detail: str) -> ProviderProbe:
    probe = ProviderProbe(name=name, url="http://127.0.0.1:8010/v1", model="m")
    probe.findings.append(Finding("chat", "failed", detail, "start your server"))
    return probe


def test_the_probe_printer_shows_no_raw_control_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console = _Console()
    monkeypatch.setattr(cli, "console", console)
    cli._print_provider_probe(_probe("local" + HOSTILE, HOSTILE))
    text = console.text
    for control in CONTROL:
        assert control not in text, repr(control)
    assert "evil" in text  # the words are still there, shown with their codes visible


def test_the_doctor_capability_row_carries_no_raw_control_characters(
    tmp_path: Path,
) -> None:
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: demo\n", encoding="utf-8")
    doctor = RactDoctor(config)
    rows = doctor._check_provider_capabilities([_probe("local", HOSTILE)])
    assert rows and rows[0].passed is False
    for control in CONTROL:
        assert control not in rows[0].message, repr(control)
        assert control not in rows[0].name, repr(control)
