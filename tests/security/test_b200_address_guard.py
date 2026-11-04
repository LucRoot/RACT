"""B-200: one address check for every route in; addresses in errors print without credentials.

The no-user-name-or-password guard (G-261) lived only in setup's question.
``RACT_BASE_URL`` / ``OPENAI_BASE_URL`` and an answers file went around it and
were printed and written; a single-token user name and short query keys passed
the pattern scan; ``describe_error`` printed the whole url; and the direct
error printers did not redact. The values here are throwaway.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import httpx
import pytest

from ract import harness, redaction
from ract.providers.capability_probe import probe_configured
from ract.providers.openai_provider import (
    QUERY_REFUSED,
    SCHEME_REFUSED,
    USERINFO_REFUSED,
    OpenAICompatibleProvider,
    address_problem,
    shown_url,
)
from ract.setup import local_probe, wizard
from tests.setup.test_wizard import _git_init, _io

TOKEN = "Tk4hR8sZq1"
SHORT = "k3y9z"


@pytest.mark.parametrize(
    ("url", "problem"),
    [
        (f"https://svc:{TOKEN}@api.example.invalid/v1", USERINFO_REFUSED),
        (f"https://{TOKEN}@api.example.invalid/v1", USERINFO_REFUSED),
        (f"https://api.example.invalid/v1?key={SHORT}", QUERY_REFUSED),
        (f"https://api.example.invalid/v1?api_key={SHORT}", QUERY_REFUSED),
        (f"https://api.example.invalid/v1?access_token={SHORT}", QUERY_REFUSED),
        (f"https://api.example.invalid/v1?x-api-key={SHORT}", QUERY_REFUSED),
        ("ftp://files.example.invalid/v1", SCHEME_REFUSED),
        ("api.example.invalid/v1", SCHEME_REFUSED),
        ("https://api.example.invalid/v1", None),
        ("http://127.0.0.1:8080/v1?model=coder", None),
    ],
)
def test_the_one_address_check(url: str, problem: str | None) -> None:
    assert address_problem(url) == problem
    if problem is not None:
        assert TOKEN not in problem and SHORT not in problem


def test_shown_url_drops_the_user_name_and_the_query() -> None:
    assert (
        shown_url(f"https://svc:{TOKEN}@h.invalid/v1?key={SHORT}")
        == "https://h.invalid/v1"
    )


@pytest.mark.parametrize("variable", local_probe.ADDRESS_VARIABLES)
def test_an_address_variable_with_credentials_is_not_used(
    variable: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(variable, f"http://{TOKEN}@192.168.1.20:8080/v1")
    asked = local_probe.candidates()
    assert all(TOKEN not in url for _label, url in asked)
    err = capsys.readouterr().err
    assert f"the address in {variable} is not used" in err and TOKEN not in err


def test_an_answers_address_with_a_query_key_is_not_used(
    capsys: pytest.CaptureFixture[str],
) -> None:
    asked = local_probe.candidates((f"http://192.168.1.20:8080/v1?key={SHORT}",))
    assert all(SHORT not in url for _label, url in asked)
    assert SHORT not in capsys.readouterr().err


def test_setup_refuses_a_typed_address_with_a_query_key(tmp_path: Path) -> None:
    _git_init(tmp_path)
    typed = f"http://192.168.1.20:8080/v1?token={SHORT}"
    probed: list[tuple[str, ...]] = []
    io_, said, _asked = _io([typed, "l", "", "skip"], [])
    io_.detect = lambda extra: probed.append(extra) or []
    assert wizard.run(tmp_path, interactive=True, io=io_) == 0
    assert all(typed not in extra for extra in probed)
    text = "\n".join(said)
    assert "that address has a key in it" in text and SHORT not in text


@pytest.mark.parametrize(
    "url",
    [f"http://{TOKEN}@127.0.0.1:9/v1", f"http://127.0.0.1:9/v1?api_key={SHORT}"],
)
def test_the_config_load_and_the_probe_refuse_it(
    url: str, tmp_path: Path, monkeypatch
) -> None:
    config = tmp_path / "ract.yaml"
    config.write_text(
        f"providers:\n  local:\n    url: {url}\n    model: m\n", encoding="utf-8"
    )
    loaded = harness._load_config(config)
    assert (
        not loaded.is_ok()
        and TOKEN not in (loaded.error or "")
        and SHORT not in (loaded.error or "")
    )

    def forbidden(*_a: object, **_k: object) -> None:
        raise AssertionError("not contacted")

    monkeypatch.setattr(httpx.Client, "post", forbidden)
    monkeypatch.setattr(httpx.Client, "get", forbidden)
    (probe,) = probe_configured({"local": {"url": url, "model": "m"}})
    assert TOKEN not in str(probe.to_dict()) and SHORT not in str(probe.to_dict())


def test_an_error_names_the_address_without_its_credentials() -> None:
    provider = OpenAICompatibleProvider(
        {"url": f"http://user:{TOKEN}@127.0.0.1:9/v1?key={SHORT}", "max_retries": 0}
    )
    request = httpx.Request("POST", "http://127.0.0.1:9/v1/chat/completions")
    for exc in (
        httpx.ConnectError("refused", request=request),
        httpx.ReadTimeout("slow", request=request),
    ):
        text = provider.describe_error(exc)
        assert TOKEN not in text and SHORT not in text, text


def test_stderr_is_redacted_line_by_line() -> None:
    key = "sk-b200-" + "Z" * 24
    redaction.register_known(key)
    try:
        out = io.StringIO()
        writer = redaction.RedactingWriter(out)
        writer.write(f"failed: HTTP 401: bad key {key[:10]}")
        assert out.getvalue() == ""  # a partial line waits for its end
        writer.write(f"{key[10:]}\nnext line\n")
        writer.flush()
        assert key not in out.getvalue() and "next line" in out.getvalue()
    finally:
        redaction.clear_known()


def test_the_cli_puts_the_redacting_writer_in_front_of_stderr(monkeypatch) -> None:
    from ract.cli import main

    monkeypatch.setattr(sys, "stderr", io.StringIO())
    main(["--version"])
    assert isinstance(sys.stderr, redaction.RedactingWriter)
