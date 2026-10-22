"""B-015: `ract setup` writes a working ract.yaml, or nothing at all."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from ract.setup import host_probe, wizard
from ract.setup.local_probe import Server
from tests.test_headless import _ract

PROFILE = host_probe.HostProfile(
    "Linux",
    "x86_64",
    "3.11.9",
    8,
    16 * host_probe.GB,
    12 * host_probe.GB,
    50 * host_probe.GB,
    "2.45.0",
    None,
)
SECRET = "sk-test-" + "Q" * 40


def _git_init(directory: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=directory, check=True)


def _io(
    replies: list[str],
    servers: list[Server],
    *,
    health_ok: bool = True,
    environ: dict[str, str] | None = None,
) -> tuple[wizard.Io, list[str], list[str]]:
    said: list[str] = []
    asked: list[str] = []
    queue = list(replies)

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return queue.pop(0) if queue else ""

    io = wizard.Io(
        ask=ask,
        say=lambda line: said.append(str(line)),
        detect=lambda extra: list(servers),
        probe=lambda: PROFILE,
        health=lambda path: wizard.Health(
            health_ok,
            0.4,
            "the model answered"
            if health_ok
            else "Request failed: nothing is answering at http://127.0.0.1:8080/v1 (connection refused).",
        ),
        environ=environ if environ is not None else {},
    )
    return io, said, asked


SERVER = Server("llama.cpp server", "http://127.0.0.1:8080/v1", ("coder-7b",))


# ------------------------------------------------------- common path (A)


def test_a_detected_server_takes_one_question(tmp_path: Path) -> None:
    _git_init(tmp_path)
    io, said, asked = _io([""], [SERVER])

    code = wizard.run(tmp_path, interactive=True, io=io)

    assert code == 0
    assert len(asked) == 1  # "Use the server at ...?"
    config = yaml.safe_load((tmp_path / "ract.yaml").read_text(encoding="utf-8"))
    assert config["providers"]["local"]["url"] == SERVER.url
    assert config["providers"]["local"]["model"] == "coder-7b"
    assert (tmp_path / "prompts" / "manager.txt").is_file()
    text = "\n".join(said)
    assert "ok: the model answered" in text
    assert text.rstrip().splitlines()[-1].startswith("Next: run `ract`")


def test_no_server_local_path_recommends_and_writes_on_skip(tmp_path: Path) -> None:
    _git_init(tmp_path)
    io, said, asked = _io(["l", "", "skip"], [])

    code = wizard.run(tmp_path, interactive=True, io=io)

    assert code == 0
    assert len(asked) == 3  # local or cloud, memory, start or skip
    text = "\n".join(said)
    assert "Suggested model: Qwen2.5-Coder 7B Instruct" in text  # 60% of 12 GB
    assert "ollama pull qwen2.5-coder:7b" in text
    config = yaml.safe_load((tmp_path / "ract.yaml").read_text(encoding="utf-8"))
    assert config["providers"]["local"]["url"] == "http://127.0.0.1:11434/v1"
    assert config["providers"]["local"]["model"] == "qwen2.5-coder:7b"


def test_a_server_found_after_guidance_keeps_its_own_model(tmp_path: Path) -> None:
    _git_init(tmp_path)
    found = iter([[], [SERVER]])
    io, _, _ = _io(["l", "", "", ""], [])
    io.detect = lambda extra: next(found)

    assert wizard.run(tmp_path, interactive=True, io=io) == 0

    config = yaml.safe_load((tmp_path / "ract.yaml").read_text(encoding="utf-8"))
    assert config["providers"]["local"]["model"] == "coder-7b"


def test_cloud_names_the_variable_and_never_the_value(tmp_path: Path) -> None:
    # D: no secret value in any output, config or prompt.
    _git_init(tmp_path)
    environ = {"OPENROUTER_API_KEY": SECRET}
    names = sorted(wizard._ENV_VARS)
    io, said, asked = _io(
        ["c", str(names.index("openrouter") + 1)], [SERVER], environ=environ
    )
    io.detect = lambda extra: []

    assert wizard.run(tmp_path, interactive=True, io=io) == 0

    written = (tmp_path / "ract.yaml").read_text(encoding="utf-8")
    assert "${OPENROUTER_API_KEY}" in written
    everything = written + "\n".join(said) + "\n".join(asked)
    assert SECRET not in everything
    assert "OPENROUTER_API_KEY is set" in "\n".join(said)


def test_an_unset_key_skips_the_check_and_says_how(tmp_path: Path) -> None:
    _git_init(tmp_path)
    answers = wizard.Answers(provider="cloud", cloud_preset="openai")
    io, said, _ = _io([], [], environ={})

    assert wizard.run(tmp_path, answers=answers, interactive=False, io=io) == 0
    text = "\n".join(said)
    assert "OPENAI_API_KEY is not set" in text
    assert "Skipped the health check" in text


def test_a_failed_health_check_keeps_the_config_and_exits_6(tmp_path: Path) -> None:
    _git_init(tmp_path)
    io, said, _ = _io([], [SERVER], health_ok=False)

    code = wizard.run(tmp_path, interactive=False, io=io)

    assert code == 6
    assert (tmp_path / "ract.yaml").is_file()
    assert "hint: start your model server" in "\n".join(said)


def test_git_init_is_offered_outside_a_repository(tmp_path: Path) -> None:
    io, said, asked = _io(["", "y"], [SERVER])

    assert wizard.run(tmp_path, interactive=True, io=io) == 0

    assert any("git init" in a for a in asked)
    assert (tmp_path / ".git").is_dir()


# ------------------------------------------------ existing config, atomicity


def test_an_existing_config_is_never_overwritten(tmp_path: Path) -> None:
    (tmp_path / "ract.yaml").write_text("mine: true\n", encoding="utf-8")
    io, said, _ = _io([], [SERVER])

    assert wizard.run(tmp_path, interactive=False, io=io) == 2
    assert (tmp_path / "ract.yaml").read_text(encoding="utf-8") == "mine: true\n"
    assert "ract setup --reconfigure" in "\n".join(said)


def test_reconfigure_writes_a_draft_and_shows_the_diff(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "ract.yaml").write_text("mine: true\n", encoding="utf-8")
    io, said, _ = _io([], [SERVER])

    code = wizard.run(
        tmp_path, answers=wizard.Answers(reconfigure=True), interactive=False, io=io
    )

    assert code == 0
    assert (tmp_path / "ract.yaml").read_text(encoding="utf-8") == "mine: true\n"
    assert "url: http://127.0.0.1:8080/v1" in (tmp_path / "ract.yaml.draft").read_text(
        encoding="utf-8"
    )
    assert "-mine: true" in "\n".join(said)


def test_ctrl_c_during_the_write_leaves_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # E: an interrupt at the rename leaves neither the config nor the temp file.
    def interrupted(src: Any, dst: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(wizard.os, "replace", interrupted)
    io, said, _ = _io([], [SERVER])

    assert wizard.run(tmp_path, interactive=False, io=io) == 5
    assert sorted(p.name for p in tmp_path.iterdir()) == []
    assert "nothing was written" in "\n".join(said)


def test_ctrl_c_at_a_question_leaves_no_file(tmp_path: Path) -> None:
    def ask(prompt: str) -> str:
        raise KeyboardInterrupt

    io, _, _ = _io([], [SERVER])
    io.ask = ask

    assert wizard.run(tmp_path, interactive=True, io=io) == 5
    assert not (tmp_path / "ract.yaml").exists()


# ----------------------------------------------- answers file, CLI (F, G)


def test_print_defaults_is_a_valid_answers_file() -> None:
    answers = wizard.Answers.from_yaml(wizard.print_defaults())
    assert answers.provider == "local" and answers.check is True


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("provider: space\n", "provider must be local or cloud"),
        ("provider: cloud\ncloud:\n  preset: nowhere\n", "unknown cloud preset"),
        ("- a list\n", "must be a YAML mapping"),
    ],
)
def test_bad_answers_are_refused(text: str, message: str) -> None:
    with pytest.raises(wizard.SetupError, match=message):
        wizard.Answers.from_yaml(text)


def test_the_cli_answers_path_runs_without_a_terminal(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = tmp_path / "ws"
    ws.mkdir()
    _git_init(ws)
    answers = ws / "answers.yaml"
    answers.write_text(
        f"provider: local\nlocal:\n  url: {server.base_url}\n", encoding="utf-8"
    )
    result = _ract(ws, "setup", "--answers", str(answers))

    assert result.returncode == 0, result.stdout + result.stderr
    config = yaml.safe_load((ws / "ract.yaml").read_text(encoding="utf-8"))
    assert config["providers"]["local"]["url"] == server.base_url
    assert "ok: the model answered" in result.stdout


def test_setup_without_a_terminal_or_answers_points_to_them(tmp_path: Path) -> None:
    result = _ract(tmp_path, "setup")

    assert result.returncode == 2
    assert "ract setup --answers FILE" in result.stderr
    assert not (tmp_path / "ract.yaml").exists()


def test_end_of_input_at_a_question_writes_nothing(tmp_path: Path) -> None:
    def ask(prompt: str) -> str:
        raise EOFError

    io, said, _ = _io([], [SERVER])
    io.ask = ask

    assert wizard.run(tmp_path, interactive=True, io=io) == 2
    assert not (tmp_path / "ract.yaml").exists()
    assert "ract setup --answers FILE" in "\n".join(said)
