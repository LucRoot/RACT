from __future__ import annotations


from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ract.cli import _release_command


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    config = tmp_path / "ract.yaml"
    config.write_text("github:\n  owner: octocat\n  repo: hello-world\n")
    return config


def test_release_list_missing_token(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result = _release_command(["list", "--config", str(config_file)])
    assert result == 1


def test_release_list_missing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    result = _release_command(["list", "--config", "does-not-exist.yaml"])
    assert result == 1


def test_release_list_missing_github_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    config = tmp_path / "ract.yaml"
    config.write_text("providers: {}\n")
    result = _release_command(["list", "--config", str(config)])
    assert result == 1


@patch("ract.cli.GitHubReleaseClient")
def test_release_list_success(
    mock_client_cls: MagicMock, config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    mock_client = MagicMock()
    mock_client.list_releases.return_value = [
        {"tag_name": "v1.0.0", "name": "First", "draft": False}
    ]
    mock_client_cls.return_value = mock_client

    result = _release_command(["list", "--config", str(config_file)])
    assert result == 0
    mock_client.list_releases.assert_called_once()


@patch("ract.cli.GitHubReleaseClient")
def test_release_create_success(
    mock_client_cls: MagicMock,
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    mock_client = MagicMock()
    mock_client.create_release.return_value = {
        "id": 2,
        "tag_name": "v1.1.0",
        "html_url": "https://github.com/octocat/hello-world/releases/v1.1.0",
    }
    mock_client.upload_asset.return_value = {
        "name": "asset.txt",
        "browser_download_url": "https://example.com/asset.txt",
    }
    mock_client_cls.return_value = mock_client

    asset = tmp_path / "asset.txt"
    asset.write_text("payload")

    result = _release_command(
        [
            "create",
            "--config",
            str(config_file),
            "--tag",
            "v1.1.0",
            "--name",
            "Release 1.1.0",
            "--body",
            "Notes",
            "--asset",
            str(asset),
            "--prerelease",
        ]
    )
    assert result == 0
    mock_client.create_release.assert_called_once_with(
        "v1.1.0", "Release 1.1.0", body="Notes", draft=False, prerelease=True
    )
    mock_client.upload_asset.assert_called_once_with(2, str(asset))


@patch("ract.cli.GitHubReleaseClient")
def test_release_create_api_error(
    mock_client_cls: MagicMock, config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    from ract.github_release import GitHubReleaseError

    mock_client = MagicMock()
    mock_client.create_release.side_effect = GitHubReleaseError("boom", 500)
    mock_client_cls.return_value = mock_client

    result = _release_command(
        [
            "create",
            "--config",
            str(config_file),
            "--tag",
            "v1.1.0",
            "--name",
            "Release 1.1.0",
        ]
    )
    assert result == 1
