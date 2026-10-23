"""S-032: a repository's `.ract/sandbox_env.allowlist` widens nothing unless trusted.

The sandbox backends read `<worktree>/.ract/sandbox_env.allowlist` and passed
the names it lists from the host environment into the sandboxed step (on
macOS, straight into `sandbox-exec`). A cloned repository could list
`HF_TOKEN` or `GITLAB_TOKEN` and its own code, running in the sandbox, got
them. Now the file is a trust item: it is honored only in a trusted
repository and only while its bytes are the ones that were trusted (D-035).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract import trust
from ract.security.manifest import CapabilityManifest
from ract.security.sandbox_macos import MacosSandbox

LISTED = "RACT_S032_PROBE_NAME"


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "state"
    home.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home))
    monkeypatch.setenv(LISTED, "value-from-the-host")
    monkeypatch.setenv("PATH", "/usr/bin")
    trust._DECIDED.clear()


def _plant(ws: Path, *names: str) -> Path:
    path = ws / ".ract" / "sandbox_env.allowlist"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f'"{name}"\n' for name in names), encoding="utf-8")
    return path


def _env(ws: Path) -> dict[str, str]:
    manifest = CapabilityManifest(run_id="s-032", env={"passthrough": ["PATH"]})
    return dict(
        MacosSandbox(sandbox_exec_path="/usr/bin/sandbox-exec").render(manifest, ws).env
    )


def test_an_untrusted_allowlist_passes_nothing(tmp_path: Path, state: None) -> None:
    ws = tmp_path / "ws"
    _plant(ws, LISTED)

    env = _env(ws)

    assert LISTED not in env, "the repository's allowlist widened the sandbox env"
    assert env.get("PATH") == "/usr/bin"


def test_the_allowlist_is_a_trust_item_and_its_bytes_are_in_the_digest(
    tmp_path: Path, state: None
) -> None:
    ws = tmp_path / "ws"
    path = _plant(ws, LISTED)

    items = [i for i in trust.trust_items(ws) if i.kind == "env"]
    assert [i.name for i in items] == ["sandbox allowlist"]
    assert LISTED in items[0].detail
    assert not trust.is_trusted(ws)
    before = trust.digest(ws)
    path.write_text(f'"{LISTED}"\n"OTHER_NAME"\n', encoding="utf-8")
    assert trust.digest(ws) != before


def test_a_trusted_allowlist_passes_its_names(tmp_path: Path, state: None) -> None:
    from ract.security.sandbox_env import trusted_repository_allowlist

    ws = tmp_path / "ws"
    _plant(ws, LISTED)
    trust.trust(ws)

    with trusted_repository_allowlist(ws):
        env = _env(ws)

    assert env.get(LISTED) == "value-from-the-host"


def test_a_file_changed_after_trust_is_ignored_at_the_next_spawn(
    tmp_path: Path, state: None
) -> None:
    from ract.security.sandbox_env import trusted_repository_allowlist

    ws = tmp_path / "ws"
    path = _plant(ws, "SOME_OTHER_NAME")
    trust.trust(ws)

    with trusted_repository_allowlist(ws):
        # A step edits the file during the run.
        path.write_text(f'"{LISTED}"\n', encoding="utf-8")
        env = _env(ws)

    assert LISTED not in env


def test_the_not_honored_note_appears_once(
    tmp_path: Path, state: None, capsys: pytest.CaptureFixture[str]
) -> None:
    from ract.security import sandbox_env

    sandbox_env._NOT_HONORED_NOTED.clear()
    ws = tmp_path / "ws"
    _plant(ws, LISTED)

    _env(ws)
    _env(ws)

    err = capsys.readouterr().err
    notes = [line for line in err.splitlines() if "is not used" in line]
    assert len(notes) == 1, err
    assert "ract trust" in err


def test_the_deny_list_still_applies_to_a_trusted_allowlist(
    tmp_path: Path, state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ract.security.sandbox_env import trusted_repository_allowlist

    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-pass")
    ws = tmp_path / "ws"
    _plant(ws, "OPENAI_API_KEY")
    trust.trust(ws)

    with trusted_repository_allowlist(ws):
        env = _env(ws)

    assert "OPENAI_API_KEY" not in env
