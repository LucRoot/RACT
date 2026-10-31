"""B-199: a user name or password in a provider address is never printed.

``_host`` returned the whole netloc, so ``https://svc:<password>@host`` put the
password (lowercased) into the withheld-key notice, the untrusted-host refusal
and the doctor's pairing advice; ``redaction.redact`` had no scheme separator
to anchor on. ``_host`` now returns the host name and the port, and an address
with credentials is refused when ract.yaml is loaded, by a sentence that does
not repeat it. The values here are throwaway.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr
from pathlib import Path

import pytest

from ract import doctor, doctor_advice, harness, trust
from ract.config_check import find_config_problems
from ract.providers.capability_probe import probe_configured
from ract.providers.openai_provider import (
    OpenAICompatibleProvider,
    _host,
    has_userinfo,
    shown_url,
)

PASSWORD = "Pw7xQ2kLm9"
TOKEN = "Tk4hR8sZq1Vb"
SHORT = "k3y9z"  # a query key shorter than 12 characters
HOST = "collector.example.invalid"
URLS = [
    f"https://svc:{PASSWORD}@{HOST}/v1",
    f"https://{TOKEN}@{HOST}/v1",
    f"https://{HOST}/v1?key={SHORT}",
]
SECRETS = (PASSWORD, TOKEN, SHORT)


def _clean(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text and secret.lower() not in text, text


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-" + "b199throwaway000000000000")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("RACT_KEY_HOSTS", raising=False)


@pytest.mark.parametrize(
    ("url", "host"),
    [
        (URLS[0], HOST),
        (URLS[1], HOST),
        (URLS[2], HOST),
        (f"https://svc:{PASSWORD}@{HOST}:8443/v1", f"{HOST}:8443"),
        ("http://[::1]:8080/v1", "[::1]:8080"),
        ("HTTPS://API.Example.Invalid/v1", "api.example.invalid"),
    ],
)
def test_the_host_is_the_host_name_and_port_only(url: str, host: str) -> None:
    assert _host(url) == host


@pytest.mark.parametrize("url", URLS)
def test_the_withheld_key_notice_never_prints_the_userinfo(url: str) -> None:
    provider = OpenAICompatibleProvider({"url": url, "api_key": "${OPENAI_API_KEY}"})
    err = io.StringIO()
    with redirect_stderr(err):
        provider._notify_withheld_key()
    assert f"was not sent to {HOST}" in err.getvalue()
    _clean(err.getvalue())


@pytest.mark.parametrize("url", URLS)
def test_the_untrusted_host_refusal_never_prints_the_userinfo(url: str) -> None:
    named = trust.repository_named_host(url)
    assert named == HOST
    _clean(named or "")


@pytest.mark.parametrize("url", URLS)
def test_the_doctor_pairing_advice_never_prints_the_userinfo(url: str) -> None:
    config = {"providers": {"remote": {"url": url, "api_key": "${OPENAI_API_KEY}"}}}
    facts = doctor._key_facts(config)
    lines = doctor_advice.advise(config, None, [], facts)
    assert any(f"with {HOST}" in line for line in lines), lines
    _clean("\n".join(lines))


@pytest.mark.parametrize("url", URLS[:2])
def test_an_address_with_credentials_is_refused_at_load(
    tmp_path: Path, url: str
) -> None:
    config = tmp_path / "ract.yaml"
    config.write_text(
        f"providers:\n  remote:\n    url: {url}\n    model: m\n", encoding="utf-8"
    )
    loaded = harness._load_config(config)
    assert not loaded.is_ok()
    assert "provider 'remote': its url carries a user name or password" in (
        loaded.error or ""
    )
    _clean(loaded.error or "")
    problems = find_config_problems(
        {"providers": {"remote": {"url": url, "model": "m"}}}
    )
    assert problems and all("user name or password" in p for p in problems)
    _clean("\n".join(problems))


@pytest.mark.parametrize("url", URLS[:2])
def test_the_probe_does_not_contact_it_and_shows_the_url_without_it(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    def forbidden(*_a: object, **_k: object) -> None:
        raise AssertionError("no request may be sent to an address with credentials")

    monkeypatch.setattr(httpx.Client, "post", forbidden)
    monkeypatch.setattr(httpx.Client, "get", forbidden)
    (probe,) = probe_configured({"remote": {"url": url, "model": "m"}})
    assert probe.url == f"https://{HOST}/v1"
    _clean(str(probe.to_dict()))


def test_the_helpers() -> None:
    assert has_userinfo(URLS[0]) and has_userinfo(URLS[1])
    assert not has_userinfo(URLS[2])
    assert shown_url(URLS[0]) == f"https://{HOST}/v1"
    # B-200: the query is dropped too, since a key may be in it.
    assert shown_url(URLS[2]) == f"https://{HOST}/v1"
