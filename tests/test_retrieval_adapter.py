# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for retrieval adapters."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import httpx
import respx

from rootact.retrieval_adapter import KeywordRetrievalAdapter, WebSearchAdapter


def test_keyword_search_finds_relevant_file(tmp_path):
    (tmp_path / "alpha.py").write_text("def search(): pass\n", encoding="utf-8")
    (tmp_path / "beta.py").write_text("def other(): pass\n", encoding="utf-8")
    adapter = KeywordRetrievalAdapter(tmp_path)
    result = adapter.search("search function", top_k=5)
    assert result.is_ok()
    results = result.unwrap()
    assert any("alpha.py" in r.source for r in results)


def test_keyword_search_root_knot_bonus(tmp_path):
    (tmp_path / "knotted.py").write_text(
        "_ROOT_KNOT = object()\ndef search(): pass\n", encoding="utf-8"
    )
    (tmp_path / "plain.py").write_text("def search(): pass\n", encoding="utf-8")
    adapter = KeywordRetrievalAdapter(tmp_path)
    result = adapter.search("search")
    results = result.unwrap()
    assert results[0].source == "knotted.py"


def test_web_search_adapter_returns_placeholder():
    adapter = WebSearchAdapter()
    result = adapter.search("latest FastAPI")
    assert not result.is_ok()


def test_web_search_adapter_requires_api_key():
    adapter = WebSearchAdapter(api_key=None)
    result = adapter.search("latest FastAPI patterns")
    assert not result.is_ok()
    assert "api_key" in result.error.lower()


def test_web_search_adapter_parses_serper_response():
    adapter = WebSearchAdapter(
        api_key="test-key", endpoint="https://google.serper.dev/search"
    )
    with respx.mock:
        route = respx.post("https://google.serper.dev/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "organic": [
                        {
                            "title": "FastAPI docs",
                            "link": "https://fastapi.tiangolo.com",
                            "snippet": "Modern web framework for Python.",
                        }
                    ]
                },
            )
        )
        result = adapter.search("FastAPI", top_k=3)
    assert result.is_ok()
    results = result.unwrap()
    assert len(results) == 1
    assert "FastAPI docs" in results[0].content
    assert "fastapi.tiangolo.com" in results[0].content
    assert route.called


def test_web_search_adapter_parses_brave_response():
    adapter = WebSearchAdapter(
        api_key="test-key",
        endpoint="https://api.search.brave.com/res/v1/web/search",
        query_param="q",
    )
    with respx.mock:
        respx.post("https://api.search.brave.com/res/v1/web/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "web": {
                        "results": [
                            {
                                "title": "Brave Search",
                                "url": "https://search.brave.com",
                                "description": "Private search engine.",
                            }
                        ]
                    }
                },
            )
        )
        result = adapter.search("brave", top_k=3)
    assert result.is_ok()
    results = result.unwrap()
    assert len(results) == 1
    assert "Brave Search" in results[0].content


def test_web_search_adapter_handles_http_error():
    adapter = WebSearchAdapter(
        api_key="test-key", endpoint="https://google.serper.dev/search"
    )
    with respx.mock:
        respx.post("https://google.serper.dev/search").mock(
            return_value=httpx.Response(429, text="rate limited")
        )
        result = adapter.search("test")
    assert not result.is_ok()
    assert "429" in result.error


def test_web_search_adapter_uses_get_method():
    adapter = WebSearchAdapter(
        api_key="test-key",
        endpoint="https://example.com/search",
        method="get",
        query_param="query",
    )
    with respx.mock:
        route = respx.get("https://example.com/search", params={"query": "hello"}).mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Hello",
                            "link": "https://hello.test",
                            "snippet": "World",
                        }
                    ]
                },
            )
        )
        result = adapter.search("hello")
    assert result.is_ok()
    assert route.called
    results = result.unwrap()
    assert results[0].source == "https://hello.test"


def test_web_search_adapter_parses_generic_result_shapes():
    shapes = [
        {"data": [{"name": "A", "url": "https://a.test", "summary": "summary A"}]},
        {"items": [{"headline": "B", "href": "https://b.test", "body": "body B"}]},
        {
            "webPages": {
                "value": [
                    {"title": "C", "url": "https://c.test", "description": "desc C"}
                ]
            }
        },
        {
            "unknown_list": [
                {"title": "D", "link": "https://d.test", "snippet": "snip D"}
            ]
        },
    ]
    for payload in shapes:
        adapter = WebSearchAdapter(
            api_key="test-key", endpoint="https://generic.test/search"
        )
        with respx.mock:
            respx.post("https://generic.test/search").mock(
                return_value=httpx.Response(200, json=payload)
            )
            result = adapter.search("query")
        assert result.is_ok(), payload
        results = result.unwrap()
        assert len(results) == 1, payload


def test_web_search_adapter_skips_bad_items():
    adapter = WebSearchAdapter(api_key="test-key", endpoint="https://serper.dev/search")
    with respx.mock:
        respx.post("https://serper.dev/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "organic": [
                        {
                            "title": "Good",
                            "link": "https://good.test",
                            "snippet": "yes",
                        },
                        "not-a-dict",
                        {"link": "https://no-title.test"},
                    ]
                },
            )
        )
        result = adapter.search("q")
    assert result.is_ok()
    results = result.unwrap()
    assert len(results) == 1
    assert "Good" in results[0].content


def test_web_search_adapter_request_error():
    adapter = WebSearchAdapter(api_key="test-key", endpoint="https://serper.dev/search")
    with respx.mock:
        respx.post("https://serper.dev/search").mock(
            side_effect=httpx.ConnectError("unreachable")
        )
        result = adapter.search("q")
    assert not result.is_ok()
    assert "unreachable" in result.error


def test_web_search_adapter_sets_brave_token_header():
    adapter = WebSearchAdapter(
        api_key="brave-key", endpoint="https://api.search.brave.com/res/v1/web/search"
    )
    with respx.mock:
        route = respx.post("https://api.search.brave.com/res/v1/web/search").mock(
            return_value=httpx.Response(200, json={"web": {"results": []}})
        )
        adapter.search("q")
    assert route.called
    assert route.calls.last.request.headers["X-Subscription-Token"] == "brave-key"


def test_keyword_search_short_query_returns_low_confidence_empty(tmp_path):
    (tmp_path / "file.py").write_text("def search(): pass\n", encoding="utf-8")
    adapter = KeywordRetrievalAdapter(tmp_path)
    result = adapter.search("a", top_k=5)
    # Query terms shorter than 3 characters are ignored, producing no results and
    # a below-floor confidence score.
    assert result.value == []
    assert result.confidence < 0.7
