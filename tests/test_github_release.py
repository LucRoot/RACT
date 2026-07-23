# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations
__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

from pathlib import Path

import httpx
import pytest
import respx

from rootact.github_release import GitHubReleaseClient, GitHubReleaseError


@pytest.fixture
def client() -> GitHubReleaseClient:
    return GitHubReleaseClient("test-token", "octocat", "hello-world")


@respx.mock
def test_list_releases(client: GitHubReleaseClient) -> None:
    route = respx.get("https://api.github.com/repos/octocat/hello-world/releases").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "tag_name": "v1.0.0"}])
    )
    releases = client.list_releases()
    assert route.called
    assert releases == [{"id": 1, "tag_name": "v1.0.0"}]


@respx.mock
def test_create_release(client: GitHubReleaseClient) -> None:
    route = respx.post(
        "https://api.github.com/repos/octocat/hello-world/releases"
    ).mock(return_value=httpx.Response(201, json={"id": 2, "tag_name": "v1.1.0"}))
    release = client.create_release("v1.1.0", "Release 1.1.0", "Some notes")
    assert route.called
    assert release["tag_name"] == "v1.1.0"
    sent = route.calls.last.request.content
    assert b"v1.1.0" in sent


@respx.mock
def test_create_release_duplicate(client: GitHubReleaseClient) -> None:
    respx.post("https://api.github.com/repos/octocat/hello-world/releases").mock(
        return_value=httpx.Response(422, json={"message": "Validation failed"})
    )
    with pytest.raises(GitHubReleaseError):
        client.create_release("v1.0.0", "Duplicate")


@respx.mock
def test_upload_asset(client: GitHubReleaseClient, tmp_path: Path) -> None:
    asset = tmp_path / "asset.txt"
    asset.write_text("payload")

    respx.get("https://api.github.com/repos/octocat/hello-world/releases/42").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 42,
                "upload_url": "https://uploads.github.com/repos/octocat/hello-world/releases/42/assets{?name,label}",
            },
        )
    )
    route = respx.post(
        "https://uploads.github.com/repos/octocat/hello-world/releases/42/assets"
    ).mock(return_value=httpx.Response(201, json={"id": 99, "name": "asset.txt"}))

    result = client.upload_asset(42, str(asset))
    assert route.called
    assert result["name"] == "asset.txt"
    request = route.calls.last.request
    assert request.url.params["name"] == "asset.txt"


@respx.mock
def test_list_releases_error(client: GitHubReleaseClient) -> None:
    respx.get("https://api.github.com/repos/octocat/hello-world/releases").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    with pytest.raises(GitHubReleaseError) as exc_info:
        client.list_releases()
    assert exc_info.value.status_code == 404
