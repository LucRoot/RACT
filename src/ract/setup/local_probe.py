"""Find a model server already running on this machine (B-015).

LR:: Setup offers a server the user already has instead of asking for a
URL. It asks only the well-known default addresses of the common local
servers, plus an address the user named in the environment, and never
sweeps a range of ports (D-007): a range probe looks like a port scan and
finds services that are not model servers. A server is offered only if it
answers ``GET /models`` like an OpenAI-compatible server, and setup shows
only what the server reports about itself.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx

from ract import egress_ledger

# (label, base URL) for the defaults of common local servers.
DEFAULT_SERVERS: tuple[tuple[str, str], ...] = (
    ("llama.cpp server", "http://127.0.0.1:8080/v1"),
    ("Ollama", "http://127.0.0.1:11434/v1"),
    ("LM Studio", "http://127.0.0.1:1234/v1"),
    ("vLLM", "http://127.0.0.1:8000/v1"),
)
# Environment variables that may name a server address.
ADDRESS_VARIABLES = ("RACT_BASE_URL", "OPENAI_BASE_URL")
PROBE_TIMEOUT = 1.5


@dataclass(frozen=True)
class Server:
    label: str
    url: str
    models: tuple[str, ...]


def candidates(extra: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """Every address setup will ask, in order, without duplicates.

    ``extra`` holds addresses the user gave setup itself (an answers file).
    """
    found: list[tuple[str, str]] = [
        ("from your answers", url.strip().rstrip("/")) for url in extra if url
    ]
    for name in ADDRESS_VARIABLES:
        value = os.environ.get(name, "").strip().rstrip("/")
        if value:
            found.append((f"from {name}", value))
    found.extend(DEFAULT_SERVERS)
    seen: set[str] = set()
    unique = []
    for label, url in found:
        if url not in seen:
            seen.add(url)
            unique.append((label, url))
    return unique


def _ask(label: str, url: str) -> Server | None:
    try:
        with (
            egress_ledger.purpose("setup"),
            # No credentials of any kind (G-056): no Authorization header,
            # and trust_env=False so httpx adds nothing from .netrc.
            egress_ledger.client(
                "setup", timeout=PROBE_TIMEOUT, trust_env=False
            ) as client,
        ):
            response = client.get(f"{url}/models")
        if response.status_code != 200:
            return None
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None  # nothing there, or not an OpenAI-compatible server
    entries = data.get("data") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return None
    models = tuple(
        str(e["id"])
        for e in entries
        if isinstance(e, dict) and isinstance(e.get("id"), str)
    )
    return Server(label=label, url=url, models=models)


def detect(extra: tuple[str, ...] = ()) -> list[Server]:
    """Servers that answered, in the order of ``candidates()``."""
    asked = candidates(extra)
    with ThreadPoolExecutor(max_workers=len(asked)) as pool:
        results = list(pool.map(lambda c: _ask(*c), asked))
    return [server for server in results if server is not None]


__all__ = ["ADDRESS_VARIABLES", "DEFAULT_SERVERS", "Server", "candidates", "detect"]
