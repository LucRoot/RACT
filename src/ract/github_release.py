"""GitHub Release client for the RACT release skill."""

from __future__ import annotations


from pathlib import Path
from typing import Any

import httpx


class GitHubReleaseError(Exception):
    """Raised when a GitHub API call fails."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class GitHubReleaseClient:
    """Thin client for listing/creating GitHub releases and uploading assets."""

    def __init__(
        self,
        token: str,
        owner: str,
        repo: str,
        base_url: str = "https://api.github.com",
    ) -> None:
        self.token = token
        self.owner = owner
        self.repo = repo
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _repo_url(self, path: str = "") -> str:
        return f"{self.base_url}/repos/{self.owner}/{self.repo}{path}"

    def list_releases(self) -> list[dict[str, Any]]:
        """Return the list of published releases for the repo."""
        with httpx.Client(headers=self._headers(), timeout=30.0) as client:
            response = client.get(self._repo_url("/releases"))
        if response.status_code != 200:
            raise GitHubReleaseError(
                f"Failed to list releases: {response.status_code} {response.text}",
                response.status_code,
            )
        return response.json()

    def create_release(
        self,
        tag: str,
        name: str,
        body: str = "",
        draft: bool = False,
        prerelease: bool = False,
    ) -> dict[str, Any]:
        """Create a new release and return the release dict."""
        payload = {
            "tag_name": tag,
            "name": name,
            "body": body,
            "draft": draft,
            "prerelease": prerelease,
        }
        with httpx.Client(headers=self._headers(), timeout=30.0) as client:
            response = client.post(self._repo_url("/releases"), json=payload)
        if response.status_code not in (201, 422):
            raise GitHubReleaseError(
                f"Failed to create release: {response.status_code} {response.text}",
                response.status_code,
            )
        data = response.json()
        if response.status_code == 422:
            raise GitHubReleaseError(
                f"Release already exists or invalid: {data}",
                response.status_code,
            )
        return data

    def upload_asset(self, release_id: int, asset_path: str) -> dict[str, Any]:
        """Upload a file asset to an existing release."""
        path = Path(asset_path)
        if not path.is_file():
            raise GitHubReleaseError(f"Asset not found: {asset_path}")

        release = self._get_release(release_id)
        upload_url = release.get("upload_url", "")
        # upload_url looks like https://uploads.../assets{?name,label}
        if "{?name,label}" in upload_url:
            upload_url = upload_url.replace("{?name,label}", f"?name={path.name}")
        elif "?name=" not in upload_url:
            upload_url = f"{upload_url}?name={path.name}"

        headers = self._headers()
        headers["Content-Type"] = "application/octet-stream"
        with httpx.Client(headers=headers, timeout=60.0) as client:
            response = client.post(upload_url, content=path.read_bytes())
        if response.status_code != 201:
            raise GitHubReleaseError(
                f"Failed to upload asset: {response.status_code} {response.text}",
                response.status_code,
            )
        return response.json()

    def _get_release(self, release_id: int) -> dict[str, Any]:
        with httpx.Client(headers=self._headers(), timeout=30.0) as client:
            response = client.get(self._repo_url(f"/releases/{release_id}"))
        if response.status_code != 200:
            raise GitHubReleaseError(
                f"Failed to fetch release {release_id}: {response.status_code}",
                response.status_code,
            )
        return response.json()
