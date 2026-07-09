# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Retrieval adapters for RACT.

Frontier agentic tools can search the web or a codebase before planning. RACT's
retrieval adapter interface makes that portable: one interface, multiple backends
(web search, local embedding index, keyword search).

LR:: The default local adapter ranks files by keyword density and Root Knot
presence. Files signed with the Root Knot get a small relevance bonus because
they are likely primary project artifacts rather than generated noise.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rootact.rooted import Rooted


@dataclass(frozen=True)
class RetrievalResult:
    """A single retrieved chunk."""

    source: str
    content: str
    score: float


class RetrievalAdapter(ABC):
    """Base class for retrieval backends."""

    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> Rooted[list[RetrievalResult]]:
        """Return the top-k results for *query*."""
        ...


class KeywordRetrievalAdapter(RetrievalAdapter):
    """Search project files by keyword density.

    This is the fallback adapter: no external API, no heavy model. It is useful
    for finding relevant files when the project is small or when the user has not
    configured an embedding index.
    """

    def __init__(
        self,
        project_dir: Path | str,
        extensions: tuple[str, ...] = (".py", ".md", ".txt", ".json", ".yaml", ".yml"),
    ) -> None:
        self.project_dir = Path(project_dir)
        self.extensions = extensions

    def _files(self) -> list[Path]:
        """Return candidate files under the project directory."""
        files: list[Path] = []
        for ext in self.extensions:
            files.extend(self.project_dir.rglob(f"*{ext}"))
        # Exclude build and hidden directories.
        return [
            f
            for f in files
            if ".rootact" not in f.parts
            and ".git" not in f.parts
            and "__pycache__" not in f.parts
        ]

    def _score(self, query: str, content: str) -> float:
        """Return a simple keyword-density score with a Root Knot bonus."""
        query_terms = [t.lower() for t in query.split() if len(t) > 2]
        if not query_terms:
            return 0.0
        content_lower = content.lower()
        hits = sum(content_lower.count(term) for term in query_terms)
        word_count = max(len(re.findall(r"\w+", content)), 1)
        density = hits / word_count
        # Root Knot artifacts are primary project source; give them a decisive but
        # still small bonus so they surface above generated noise in close calls.
        bonus = 0.25 if "_ROOT_KNOT = object()" in content else 0.0
        return density + bonus

    def search(self, query: str, top_k: int = 5) -> Rooted[list[RetrievalResult]]:
        """Return the top-k matching file snippets."""
        scored: list[tuple[float, Path, str]] = []
        for path in self._files():
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            score = self._score(query, content)
            if score > 0:
                scored.append((score, path, content))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [
            RetrievalResult(
                source=str(path.relative_to(self.project_dir)),
                content=content[:2000],
                score=score,
            )
            for score, path, content in scored[:top_k]
        ]
        return Rooted(
            value=results,
            assumption="Keyword retrieval ranks project files by query relevance.",
            confidence=0.8 if results else 0.3,
            provenance=["retrieval_adapter.keyword"],
        )


class WebSearchAdapter(RetrievalAdapter):
    """Web-search retrieval backend for RACT.

    Calls a configurable search API endpoint and normalizes the response into
    `RetrievalResult` objects. Works out of the box with Serper, Brave, Bing,
    and any API that returns a JSON list of results with title/link/snippet
    fields.

    LR:: The adapter is intentionally provider-agnostic. RACT users bring their
    own search API key; the tool does not ship with bundled credentials.
    """

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str | None = None,
        query_param: str = "q",
        method: str = "post",
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint or "https://google.serper.dev/search"
        self.query_param = query_param
        self.method = method.lower()
        self.headers = headers or {}
        self.timeout = timeout

    def _request_payload(self, query: str) -> dict[str, Any]:
        """Build the request body/query parameters for the search API."""
        payload: dict[str, Any] = {self.query_param: query}
        if self.api_key and "x-api-key" not in {k.lower() for k in self.headers}:
            # Serper uses x-api-key; Brave uses X-Subscription-Token.
            if "brave" in self.endpoint.lower():
                self.headers["X-Subscription-Token"] = self.api_key
            else:
                self.headers["X-API-Key"] = self.api_key
        return payload

    def _parse_results(self, data: dict[str, Any]) -> list[RetrievalResult]:
        """Normalize common search API response shapes."""
        candidates: list[dict[str, Any]] = []

        # Serper.dev shape.
        if "organic" in data and isinstance(data["organic"], list):
            candidates = data["organic"]
        # Brave shape.
        elif isinstance(data.get("web"), dict) and isinstance(
            data["web"].get("results"), list
        ):
            candidates = data["web"]["results"]
        # Generic shapes.
        elif isinstance(data.get("results"), list):
            candidates = data["results"]
        elif isinstance(data.get("data"), list):
            candidates = data["data"]
        elif isinstance(data.get("items"), list):
            candidates = data["items"]
        elif isinstance(data.get("webPages"), dict) and isinstance(
            data["webPages"].get("value"), list
        ):
            candidates = data["webPages"]["value"]
        else:
            # Last resort: any top-level list of dicts.
            for value in data.values():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    candidates = value
                    break

        results: list[RetrievalResult] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            title = self._first_key(item, ["title", "name", "headline"])
            url = self._first_key(item, ["link", "url", "href", "url_permalink"])
            snippet = self._first_key(
                item, ["snippet", "description", "summary", "body", "content"]
            )
            if not (title or snippet):
                continue
            text = f"{title or ''}\n{url or ''}\n{snippet or ''}".strip()
            results.append(
                RetrievalResult(
                    source=url or "web",
                    content=text,
                    score=0.0,
                )
            )
        return results

    @staticmethod
    def _first_key(data: dict[str, Any], keys: list[str]) -> str:
        """Return the first present string value for any of *keys*."""
        for key in keys:
            value = data.get(key)
            if isinstance(value, str):
                return value
        return ""

    def search(self, query: str, top_k: int = 5) -> Rooted[list[RetrievalResult]]:
        """Search the web and return normalized snippets."""
        if not self.api_key:
            return Rooted(
                value=None,
                assumption="Web search adapter is configured with an API key.",
                confidence=0.0,
                provenance=["retrieval_adapter.web"],
                error="Web search adapter requires an api_key. Configure retrieval.api_key in rootact.yaml.",
            )

        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            return Rooted(
                value=None,
                assumption="httpx is installed.",
                confidence=0.0,
                provenance=["retrieval_adapter.web"],
                error=f"httpx is required for web search: {exc}",
            )

        payload = self._request_payload(query)
        try:
            if self.method == "get":
                response = httpx.get(
                    self.endpoint,
                    params=payload,
                    headers=self.headers,
                    timeout=self.timeout,
                )
            else:
                response = httpx.post(
                    self.endpoint,
                    json=payload,
                    headers=self.headers,
                    timeout=self.timeout,
                )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            return Rooted(
                value=None,
                assumption="Search API returns a successful status.",
                confidence=0.0,
                provenance=["retrieval_adapter.web"],
                error=f"Search API returned {exc.response.status_code}: {exc.response.text[:200]}",
            )
        except httpx.RequestError as exc:
            return Rooted(
                value=None,
                assumption="Search API is reachable.",
                confidence=0.0,
                provenance=["retrieval_adapter.web"],
                error=f"Search API request failed: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return Rooted(
                value=None,
                assumption="Search API response is valid JSON.",
                confidence=0.0,
                provenance=["retrieval_adapter.web"],
                error=f"Failed to call search API: {exc}",
            )

        results = self._parse_results(data)[:top_k]
        return Rooted(
            value=results,
            assumption="Search API returns relevant results for the query.",
            confidence=0.8 if results else 0.2,
            provenance=["retrieval_adapter.web", self.endpoint],
        )


# RACT 0.1.1 - Trust and Tooling
