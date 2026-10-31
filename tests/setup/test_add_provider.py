"""B-160c: `ract setup --add-provider` adds a second endpoint (setup case 4)."""

from __future__ import annotations

from pathlib import Path

import yaml

from ract.setup import wizard
from tests.setup.test_wizard import SECRET, SERVER, _git_init, _io


def _first_setup(tmp_path: Path) -> None:
    _git_init(tmp_path)
    io, _, _ = _io([""], [SERVER])
    assert wizard.run(tmp_path, interactive=True, io=io) == 0


def _config(tmp_path: Path) -> dict:
    return yaml.safe_load((tmp_path / "ract.yaml").read_text(encoding="utf-8"))


def test_a_cloud_provider_is_added_beside_the_local_one(tmp_path: Path) -> None:
    _first_setup(tmp_path)
    names = sorted(wizard._ENV_VARS)
    io, said, asked = _io(
        ["", "c", str(names.index("openrouter") + 1), "y"],
        [],
        environ={"OPENROUTER_API_KEY": SECRET},
    )
    checked: list[dict] = []

    def health(path: Path) -> wizard.Health:
        checked.append(yaml.safe_load(path.read_text(encoding="utf-8")))
        return wizard.Health(True, 0.2, "the model answered")

    io.health = health

    answers = wizard.Answers(add_provider=True)
    assert wizard.run(tmp_path, answers=answers, interactive=True, io=io) == 0

    config = _config(tmp_path)
    assert set(config["providers"]) == {"local", "openrouter"}
    assert config["manager_provider"] == "local"  # left as it was
    text = "\n".join(said)
    assert "Adds the provider 'openrouter' to ract.yaml:" in text
    assert "+  openrouter:" in text  # the difference is shown before writing
    assert any("Write it to ract.yaml?" in a for a in asked)
    assert checked and checked[0]["manager_provider"] == "openrouter"  # the new one
    assert "ok: the model answered" in text
    assert SECRET not in (tmp_path / "ract.yaml").read_text(encoding="utf-8") + text


def test_the_same_name_gets_a_number_and_replaces_nothing(tmp_path: Path) -> None:
    _first_setup(tmp_path)
    other = wizard.local_probe.Server(
        "llama.cpp server", "http://127.0.0.1:8081/v1", ("other-7b",)
    )
    io, _, _ = _io(["", "y"], [other])

    answers = wizard.Answers(add_provider=True)
    assert wizard.run(tmp_path, answers=answers, interactive=True, io=io) == 0

    config = _config(tmp_path)
    assert config["providers"]["local"]["url"] == SERVER.url
    assert config["providers"]["local_2"]["url"] == other.url


def test_answering_no_changes_nothing(tmp_path: Path) -> None:
    _first_setup(tmp_path)
    before = (tmp_path / "ract.yaml").read_text(encoding="utf-8")
    io, said, _ = _io(["", "n"], [SERVER])

    answers = wizard.Answers(add_provider=True)
    assert wizard.run(tmp_path, answers=answers, interactive=True, io=io) == 0

    assert (tmp_path / "ract.yaml").read_text(encoding="utf-8") == before
    assert "Nothing was changed." in said


def test_without_a_config_there_is_nothing_to_add_to(tmp_path: Path) -> None:
    _git_init(tmp_path)
    io, said, _ = _io([], [SERVER])

    answers = wizard.Answers(add_provider=True)
    assert wizard.run(tmp_path, answers=answers, interactive=True, io=io) == 2
    assert not (tmp_path / "ract.yaml").exists()
    assert any("nothing to add to" in line for line in said)
