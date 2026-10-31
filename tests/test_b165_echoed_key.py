"""B-165: a server that echoes the key in its error body never gets the key printed.

MASON's wrong-key setup walk: the fake server's 401 body repeated the
Authorization header, and setup printed it in full inside ``failed: HTTP 401``.
The key here is a throwaway value; the server is on loopback.
"""

from __future__ import annotations

import http.server
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from ract.providers.openai_provider import OpenAICompatibleProvider
from ract.setup import wizard
from tests.setup.test_wizard import _git_init

THROWAWAY = "sk-throwaway-b165-" + "E" * 32


class _Echo(http.server.BaseHTTPRequestHandler):
    """Answers 401 and repeats every request header in the body."""

    def _echo(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        # Credential headers first, so the echo sits inside a 200-character cut.
        items = sorted(
            self.headers.items(),
            key=lambda kv: (
                0 if ("auth" in kv[0].lower() or "key" in kv[0].lower()) else 1
            ),
        )
        echoed = " | ".join(f"{k}: {v}" for k, v in items)
        body = (
            '{"error": {"message": "Incorrect API key provided: ' + echoed + '"}}'
        ).encode("utf-8")
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = _echo  # noqa: N815 - http.server names
    do_GET = _echo  # noqa: N815

    def log_message(self, *args: object) -> None:
        return


@pytest.fixture
def echo(monkeypatch) -> Iterator[str]:
    server = http.server.HTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host = f"127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv("OPENAI_API_KEY", THROWAWAY)
    monkeypatch.setenv("RACT_KEY_HOSTS", f"OPENAI_API_KEY={host}")
    monkeypatch.setenv("RACT_NO_NETWORK", "1")
    try:
        yield f"http://{host}/v1"
    finally:
        server.shutdown()


def _provider(url: str) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider({"url": url, "max_retries": 0, "model": "m"})


def test_the_error_of_a_completion_holds_no_echoed_key(echo: str) -> None:
    provider = _provider(echo)
    assert provider.api_key == THROWAWAY  # paired, so the key was sent and echoed
    result = provider.complete([{"role": "user", "content": "hi"}], max_tokens=4)
    assert not result.is_ok()
    assert "HTTP 401" in (result.error or "")
    assert THROWAWAY not in (result.error or "")


def test_the_error_of_a_stream_holds_no_echoed_key(echo: str) -> None:
    provider = _provider(echo)
    errors = [
        chunk.error or ""
        for chunk in provider.complete_stream(
            [{"role": "user", "content": "hi"}], max_tokens=4
        )
        if not chunk.is_ok()
    ]
    assert errors and all(THROWAWAY not in e for e in errors)
    assert any("HTTP 401" in e for e in errors)


def test_setup_prints_no_echoed_key_and_writes_none(
    tmp_path: Path, monkeypatch, echo: str
) -> None:
    monkeypatch.setenv("RACT_PRESET_BASE_URL", f"openai={echo}")
    _git_init(tmp_path)
    said: list[str] = []
    asked: list[str] = []
    io = wizard.Io(
        ask=lambda prompt: asked.append(prompt) or "",
        say=lambda line: said.append(str(line)),
        detect=lambda extra: [],
        width=lambda: 10_000,
    )
    answers = wizard.Answers(provider="cloud", cloud_preset="openai")

    code = wizard.run(tmp_path, answers=answers, interactive=False, io=io)

    transcript = "\n".join(said + asked)
    assert code == wizard.EXIT_PROVIDER and "failed: HTTP 401" in transcript
    assert THROWAWAY not in transcript
    # ract.yaml is checked on its own, apart from the transcript.
    written = (tmp_path / "ract.yaml").read_text(encoding="utf-8")
    assert THROWAWAY not in written
    assert (
        yaml.safe_load(written)["providers"]["openai"]["api_key"] == "${OPENAI_API_KEY}"
    )


def test_a_search_error_holds_no_echoed_key(echo: str) -> None:
    # G-271 (1): retrieval_adapter's search error printed the body raw.
    from ract.retrieval_adapter import WebSearchAdapter

    adapter = WebSearchAdapter(api_key=THROWAWAY, endpoint=echo + "/search")
    result = adapter.search("q")
    assert not result.is_ok() and "401" in (result.error or "")
    assert THROWAWAY not in (result.error or "")


def test_a_github_release_error_holds_no_echoed_token(echo: str) -> None:
    # G-271 (2): github_release printed the whole body in three messages.
    from ract.github_release import GitHubReleaseClient, GitHubReleaseError

    client = GitHubReleaseClient(
        token=THROWAWAY, owner="o", repo="r", base_url=echo.removesuffix("/v1")
    )
    with pytest.raises(GitHubReleaseError) as info:
        client.list_releases()
    assert "401" in str(info.value) and THROWAWAY not in str(info.value)


def test_a_key_at_the_cut_is_masked_whole() -> None:
    from ract import redaction

    redaction.register_known(THROWAWAY)
    text = "x" * 190 + THROWAWAY + " tail"
    out = redaction.body(text, 200)
    assert THROWAWAY[:10] not in out and len(out) <= 200


def test_a_headless_run_writes_and_prints_no_echoed_key(
    tmp_path: Path, echo: str
) -> None:
    # G-269's list: the headless error object, the events log, the ledger and every
    # file written. Every state folder points into tmp_path so all of it is scanned.
    import os
    import subprocess
    import sys

    from ract.provider_presets import get_preset

    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    config = get_preset("openai")
    config["providers"]["openai"]["url"] = echo
    config["providers"]["openai"]["max_retries"] = 0
    (project / "ract.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    state = tmp_path / "state"
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": os.pathsep.join([str(root / "src"), str(root)]),
            "LOCALAPPDATA": str(state / "local"),
            "APPDATA": str(state / "roaming"),
            "XDG_STATE_HOME": str(state / "xdg"),
            "HOME": str(state / "home"),
            "USERPROFILE": str(state / "home"),
        }
    )
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "-p",
            "--ask",
            "hi",
            "--output-format",
            "json",
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    out = done.stdout + done.stderr
    assert done.returncode != 0 and "401" in out, out[-400:]
    assert THROWAWAY not in out
    # The echo did happen (so the check is not vacuous): it arrives masked.
    assert "[redacted]" in out
    leaks = [
        str(p)
        for base in (project, state)
        for p in base.rglob("*")
        if p.is_file()
        and ".git" not in p.parts
        and THROWAWAY in p.read_text(encoding="utf-8", errors="replace")
    ]
    assert leaks == []
