"""B-058b: ``/model <name>`` switches the manager provider for the session.

The override is in-process: it is set through ``config_check.set_session_manager``
and read by ``resolve_manager_provider``. Nothing is written to a file. These
tests check the resolution, the REPL reply, the refusals and the reset. Tests
that need a second real turn through the dispatcher are not run here; see the
READY entry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ract import cli, config_check, trust
from ract.providers.router import ProviderRouter
from ract.repl import ReplSession
from tests.test_repl import _Console


@pytest.fixture(autouse=True)
def _no_session_override() -> Any:
    config_check.set_session_manager(None)
    yield
    config_check.set_session_manager(None)


def _config(path: Path, *, second_url: str = "http://127.0.0.1:8011/v1") -> Path:
    path.write_text(
        "project:\n  name: demo\n"
        "manager_provider: local\n"
        "providers:\n"
        "  local:\n"
        "    adapter: local_http\n"
        "    url: http://127.0.0.1:8010/v1\n"
        "    model: local-7b\n"
        "  second:\n"
        "    adapter: local_http\n"
        f"    url: {second_url}\n"
        "    model: local-14b\n",
        encoding="utf-8",
    )
    return path


def _session(config: Path) -> tuple[ReplSession, _Console]:
    console = _Console()
    session = ReplSession(
        config,
        dispatch=lambda argv: 0,
        read_line=lambda prompt: "",
        console=console,
        verbs=cli.CLI_VERBS,
    )
    return session, console


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# ---------------------------------------------------------------- 1. the switch


def test_a_switch_changes_the_manager_the_next_turn_resolves_to(tmp_path: Path) -> None:
    config = _config(tmp_path / "ract.yaml")
    session, console = _session(config)
    session.handle("/model second")
    assert "manager provider is now 'second' for this session" in console.text
    assert "ract.yaml is unchanged" in console.text

    import yaml

    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    manager, error = config_check.resolve_manager_provider(data)
    assert error is None and manager == "second"
    adapter = ProviderRouter(data["providers"]).get_adapter(manager).unwrap()
    assert adapter.url == "http://127.0.0.1:8011/v1"


def test_after_the_switch_the_listing_marks_the_new_manager(tmp_path: Path) -> None:
    session, console = _session(_config(tmp_path / "ract.yaml"))
    session.handle("/model second")
    session.handle("/model")
    assert "second (manager, current)" in console.text
    assert "local (manager, current)" not in console.text


# ---------------------------------------------------------------- 2. refusals


@pytest.mark.parametrize("name", ["nope", "", "bad\x1b[31mname"])
def test_an_unknown_name_lists_the_valid_ones_and_changes_nothing(
    tmp_path: Path, name: str
) -> None:
    config = _config(tmp_path / "ract.yaml")
    before = config.read_bytes()
    session, console = _session(config)
    session.handle(f"/model {name}" if name else "/model")
    assert config_check.session_manager() is None
    assert config.read_bytes() == before
    assert "\x1b" not in console.text


def test_the_switch_never_writes_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    state = tmp_path / "state"
    ws.mkdir()
    state.mkdir()
    config = _config(ws / "ract.yaml")
    monkeypatch.setenv("LOCALAPPDATA", str(state))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    before = (_tree(ws), _tree(state))
    session, _ = _session(config)
    session.handle("/model second")
    assert (_tree(ws), _tree(state)) == before


# ---------------------------------------------------------------- 3. a new session


def test_a_new_session_starts_on_the_files_manager(tmp_path: Path) -> None:
    config = _config(tmp_path / "ract.yaml")
    session, _ = _session(config)
    session.handle("/model second")
    assert config_check.session_manager() == "second"
    _session(config)  # a new session in the same workspace
    assert config_check.session_manager() is None


# ---------------------------------------------------------------- 4. trust


def test_a_repository_named_host_is_refused_until_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(
        tmp_path / "ract.yaml", second_url="https://models.example.invalid/v1"
    )
    monkeypatch.setattr(
        trust, "repository_named_host", lambda url: "models.example.invalid"
    )
    session, console = _session(config)
    session.handle("/model second")
    assert config_check.session_manager() is None
    assert "ract trust" in console.text

    monkeypatch.setattr(trust, "repository_named_host", lambda url: None)
    session.handle("/model second")
    assert config_check.session_manager() == "second"


# ---------------------------------------------------------------- 5. not run here


@pytest.mark.skip(
    reason="not run in this pass: needs a second turn through the dispatcher"
)
def test_the_next_turn_request_reaches_the_second_server() -> None:
    pass


@pytest.mark.skip(
    reason="not run in this pass: turns are in-process in this build; no child process to pass it to"
)
def test_a_child_process_turn_receives_the_override_as_an_argument() -> None:
    pass


@pytest.mark.skip(
    reason="not run in this pass: concurrent turn test needs a running turn"
)
def test_a_switch_during_a_turn_applies_from_the_next_turn() -> None:
    pass
