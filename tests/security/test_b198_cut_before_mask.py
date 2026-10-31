"""B-198: a response body or exception text is masked whole, then cut.

``capability_probe._explain`` cut a 401 body at 120 characters and then masked
the provider's key by exact match, so a key across the cut was printed in part
by ``ract doctor --check-providers`` (human and ``--json``). Every cut of a
response body or of exception text in ``src`` now goes through
``redaction.body``; the sweep at the end keeps it so.

The keys here are throwaway values made for the test.
"""

from __future__ import annotations

import ast
import base64
import json
import secrets
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from ract import doctor_advice, redaction
from ract.providers.capability_probe import ProviderProbe, probe_provider
from ract.providers.openai_provider import OpenAICompatibleProvider

URL = "http://127.0.0.1:9/v1"
MODEL = "probe-model"
SRC = Path(__file__).resolve().parents[2] / "src" / "ract"


@pytest.fixture
def key() -> Iterator[str]:
    value = "sk-b198-" + secrets.token_hex(16)
    yield value
    redaction.clear_known()


def _probe(key: str, body: str) -> ProviderProbe:
    def refusing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=body)

    provider = OpenAICompatibleProvider(
        {"url": URL, "model": MODEL, "api_key": key, "max_retries": 0}
    )
    provider._client = httpx.Client(transport=httpx.MockTransport(refusing))
    return probe_provider("local", provider, url=URL, model=MODEL)


def _printed(probe: ProviderProbe) -> str:
    """What the human table, the advice block and ``--json`` show of the probe."""
    advice = doctor_advice.advise(
        {"providers": {"local": {"url": URL, "model": MODEL}}}, None, [probe], []
    )
    detail = next(f.detail for f in probe.findings if f.label == "chat")
    return "\n".join([detail, *advice, json.dumps(probe.to_dict())])


def _no_piece_of(secret: str, text: str, piece: int = 6) -> None:
    for i in range(len(secret) - piece + 1):
        assert secret[i : i + piece] not in text, (secret[i : i + piece], text)


@pytest.mark.parametrize("offset", range(0, 121))
def test_the_key_split_by_the_cut_is_not_printed(key: str, offset: int) -> None:
    body = "e" * offset + key + " is not a valid key"
    _no_piece_of(key, _printed(_probe(key, body)))


@pytest.mark.parametrize("offset", [0, 60, 100, 110, 119])
@pytest.mark.parametrize("form", ["url", "base64", "urlsafe"])
def test_an_encoded_key_split_by_the_cut_is_not_printed(
    key: str, offset: int, form: str
) -> None:
    redaction.register_known(key)  # as resolving the provider's key does
    encoded = {
        "url": quote(key, safe=""),
        "base64": base64.b64encode(key.encode()).decode(),
        "urlsafe": base64.urlsafe_b64encode(key.encode()).decode(),
    }[form]
    body = "e" * offset + encoded + " was sent"
    _no_piece_of(encoded, _printed(_probe(key, body)))


def test_a_short_body_is_still_shown(key: str) -> None:
    printed = _printed(_probe(key, "invalid key"))
    assert "HTTP 401: invalid key" in printed


# ------------------------------------------------------------------ the sweep

# Names that hold exception text or a server's reply in src.
_EXC_NAMES = {"exc", "err", "error", "e"}
_REPLY_NAMES = {"response", "reply", "body_text"}


def _names_in(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)
    }


def _is_cut(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Slice)
        and node.slice.lower is None
        and node.slice.upper is not None
    )


def _sliced_text(node: ast.Subscript) -> bool:
    """True when the sliced value is exception text or a reply body."""
    value = node.value
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        if value.func.id == "str" and value.args:
            return bool(_names_in(value.args[0]) & _EXC_NAMES)
    if isinstance(value, ast.Name):
        return value.id in _REPLY_NAMES or value.id in _EXC_NAMES
    if isinstance(value, ast.Attribute) and value.attr == "text":
        return "response" in _names_in(value.value)
    has_fstring_exc = any(
        isinstance(n, ast.FormattedValue) and _names_in(n.value) & _EXC_NAMES
        for n in ast.walk(value)
    )
    return has_fstring_exc


def _unmasked_cuts(tree: ast.AST) -> Iterator[ast.Subscript]:
    def visit(node: ast.AST, masked: bool) -> Iterator[ast.Subscript]:
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "body"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "redaction"
        ):
            masked = True
        if not masked and _is_cut(node) and _sliced_text(node):  # type: ignore[arg-type]
            yield node  # type: ignore[misc]
        for child in ast.iter_child_nodes(node):
            yield from visit(child, masked)

    yield from visit(tree, False)


def test_no_response_body_or_exception_text_is_cut_before_it_is_masked() -> None:
    found: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in _unmasked_cuts(tree):
            found.append(f"{path.relative_to(SRC).as_posix()}:{node.lineno}")
    assert found == [], "cut before redaction.body: " + ", ".join(found)


def test_the_sweep_finds_the_old_shapes() -> None:
    old = (
        "x = str(exc)[:512]\n"
        "y = exc.response.text[:120]\n"
        "z = response[:200]\n"
        "w = ' '.join(f'{type(exc).__name__}: {exc}'.split())[:120]\n"
        "ok = redaction.body(str(exc), 512)\n"
    )
    lines = sorted(node.lineno for node in _unmasked_cuts(ast.parse(old)))
    assert lines == [1, 2, 3, 4]
