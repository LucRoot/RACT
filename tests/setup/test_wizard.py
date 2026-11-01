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
        width=lambda: 10_000,  # these tests read whole lines; B-163's test sets widths
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
    io, said, asked = _io(["", "l", "", "skip"], [])

    code = wizard.run(tmp_path, interactive=True, io=io)

    assert code == 0
    assert len(asked) == 4  # address, local or cloud, memory, start or skip
    text = "\n".join(said)
    assert "Suggested model: Qwen2.5-Coder 7B Instruct" in text  # 60% of 12 GB
    assert "ollama pull qwen2.5-coder:7b" in text
    config = yaml.safe_load((tmp_path / "ract.yaml").read_text(encoding="utf-8"))
    assert config["providers"]["local"]["url"] == "http://127.0.0.1:11434/v1"
    assert config["providers"]["local"]["model"] == "qwen2.5-coder:7b"


def test_a_server_found_after_guidance_keeps_its_own_model(tmp_path: Path) -> None:
    _git_init(tmp_path)
    found = iter([[], [SERVER]])
    io, _, _ = _io(["", "l", "", "", ""], [])
    io.detect = lambda extra: next(found)

    assert wizard.run(tmp_path, interactive=True, io=io) == 0

    config = yaml.safe_load((tmp_path / "ract.yaml").read_text(encoding="utf-8"))
    assert config["providers"]["local"]["model"] == "coder-7b"


def test_presets_without_a_key_say_no_key_needed(tmp_path: Path) -> None:
    # B-160e: the local presets printed "(key in )" with nothing after "in".
    _git_init(tmp_path)
    names = sorted(wizard._ENV_VARS)
    keyless = [n for n in names if not wizard._ENV_VARS[n]]
    assert {"llamacpp", "lmstudio", "ollama", "vllm"} <= set(keyless)
    io, said, _ = _io(["", "c", str(names.index("ollama") + 1)], [SERVER])
    io.detect = lambda extra: []

    assert wizard.run(tmp_path, interactive=True, io=io) == 0

    text = "\n".join(said)
    assert "(key in )" not in text and "${}" not in text
    for name in keyless:
        assert f") {name}  (no key needed)" in text
    for name in set(names) - set(keyless):
        assert f") {name}  (key in {wizard._ENV_VARS[name]})" in text
    assert "  key variable: none (no key needed)" in text


def test_a_picked_preset_shows_its_address_and_variable(tmp_path: Path) -> None:
    # B-160b: one line each; the key's value is never shown.
    _git_init(tmp_path)
    names = sorted(wizard._ENV_VARS)
    io, said, asked = _io(
        ["", "c", str(names.index("openrouter") + 1)],
        [],
        environ={"OPENROUTER_API_KEY": SECRET},
    )

    assert wizard.run(tmp_path, interactive=True, io=io) == 0

    url = wizard.get_preset("openrouter")["providers"]["openrouter"]["url"]
    assert f"  address: {url}" in said
    assert "  key variable: OPENROUTER_API_KEY" in said
    assert SECRET not in "\n".join(said + asked)


def test_cloud_names_the_variable_and_never_the_value(tmp_path: Path) -> None:
    # D: no secret value in any output, config or prompt.
    _git_init(tmp_path)
    environ = {"OPENROUTER_API_KEY": SECRET}
    names = sorted(wizard._ENV_VARS)
    io, said, asked = _io(
        ["", "c", str(names.index("openrouter") + 1)], [SERVER], environ=environ
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


def test_an_answers_file_with_a_key_is_refused(tmp_path: Path) -> None:
    # G-056: setup never takes a key value, not even from a file.
    answers = tmp_path / "answers.yaml"
    answers.write_text(
        "provider: cloud\ncloud:\n  preset: openai\n  api_key: sk-proj-"
        + "A" * 48
        + "\n",
        encoding="utf-8",
    )

    result = _ract(tmp_path, "setup", "--answers", str(answers))

    assert result.returncode == 2
    assert "Setup never takes a key" in result.stderr
    assert "sk-proj-" not in result.stdout + result.stderr
    assert not (tmp_path / "ract.yaml").exists()


def test_a_config_written_by_setup_raises_no_trust_question(tmp_path: Path) -> None:
    # G-056: the config is the operator's own; nothing in it needs trust.
    from ract import trust

    _git_init(tmp_path)
    io, _, _ = _io([], [SERVER])
    assert wizard.run(tmp_path, interactive=False, io=io) == 0

    assert trust.trust_items(tmp_path) == []


def test_a_server_with_no_model_is_not_offered(tmp_path: Path) -> None:
    # S3 walkthrough: the placeholder model failed every request.
    _git_init(tmp_path)
    empty = Server("Ollama's default address", "http://127.0.0.1:11434/v1", ())
    io, said, asked = _io(["c", "1"], [empty])

    assert wizard.run(tmp_path, interactive=True, io=io) == 0

    text = "\n".join(said)
    assert "lists no model yet; load one in it" in text
    assert not any("Use the server" in a for a in asked)


OTHER = Server("llama.cpp server", "http://192.168.1.20:8080/v1", ("coder-7b",))


def test_a_typed_address_that_answers_is_written(tmp_path: Path) -> None:
    # B-160a, setup case 2: a server on another address.
    _git_init(tmp_path)
    io, said, asked = _io([OTHER.url, ""], [])
    io.detect = lambda extra: [OTHER] if OTHER.url in extra else []

    assert wizard.run(tmp_path, interactive=True, io=io) == 0

    assert asked[0] == wizard.ADDRESS_QUESTION
    config = yaml.safe_load((tmp_path / "ract.yaml").read_text(encoding="utf-8"))
    assert config["providers"]["local"]["url"] == OTHER.url
    assert config["providers"]["local"]["model"] == "coder-7b"


def test_an_address_with_a_password_is_refused_before_any_probe(
    tmp_path: Path,
) -> None:
    # G-261: it would be written to ract.yaml; it is not probed nor echoed.
    _git_init(tmp_path)
    secret_address = "http://user:hunter2-pass@192.168.1.20:8080/v1"
    probed: list[tuple[str, ...]] = []
    io, said, asked = _io([secret_address, "l", "", "skip"], [])
    io.detect = lambda extra: probed.append(extra) or []

    assert wizard.run(tmp_path, interactive=True, io=io) == 0

    assert all(secret_address not in extra for extra in probed)
    text = "\n".join(said)
    assert "has a user name or password in it" in text
    assert "hunter2-pass" not in text
    assert "hunter2-pass" not in (tmp_path / "ract.yaml").read_text(encoding="utf-8")


def test_a_typed_address_that_does_not_answer_writes_nothing_for_it(
    tmp_path: Path,
) -> None:
    _git_init(tmp_path)
    io, said, asked = _io(["http://192.168.1.99:8080/v1", "l", "", ""], [])

    assert wizard.run(tmp_path, interactive=True, io=io) == wizard.EXIT_PROVIDER

    text = "\n".join(said)
    assert "nothing answered at http://192.168.1.99:8080/v1" in text
    assert "no config written" in text
    assert not (tmp_path / "ract.yaml").exists()


def test_looking_again_and_finding_nothing_writes_no_config(tmp_path: Path) -> None:
    # MASON's walk: Enter at "look again" with nothing answering wrote an Ollama
    # default whose check then said connection refused.
    _git_init(tmp_path)
    io, said, _ = _io(["", "l", "", ""], [])

    assert wizard.run(tmp_path, interactive=True, io=io) == wizard.EXIT_PROVIDER

    assert not (tmp_path / "ract.yaml").exists()
    assert "Still nothing to use; no config written." in "\n".join(said)


def test_nothing_answering_is_said(tmp_path: Path) -> None:
    _git_init(tmp_path)
    io, said, _ = _io([], [])

    wizard.run(tmp_path, interactive=False, io=io)

    assert "  nothing answered" in said


def test_setup_from_bare_ract_says_the_session_opens(tmp_path: Path) -> None:
    _git_init(tmp_path)
    io, said, _ = _io([""], [SERVER])

    wizard.run(tmp_path, interactive=True, io=io, opens_session=True)

    assert said[-1].startswith("Opening the session")


def test_the_memory_suggestion_follows_the_machine_not_the_minute(
    tmp_path: Path,
) -> None:
    # G-059: 64 GB machine with 4 GB free right now (a busy machine).
    _git_init(tmp_path)
    busy = host_probe.HostProfile(
        "Linux",
        "x86_64",
        "3.11.9",
        8,
        64 * host_probe.GB,
        4 * host_probe.GB,
        50 * host_probe.GB,
        "2.45.0",
        None,
    )
    io, said, asked = _io(["", "l", "", "skip"], [])
    io.probe = lambda: busy

    assert wizard.run(tmp_path, interactive=True, io=io) == 0

    text = "\n".join(said)
    assert "this machine has 64 GB, 4.0 GB free right now" in text
    assert any("[38.4]" in a for a in asked)  # 60 percent of the total
    assert "Suggested model: Qwen2.5-Coder 32B Instruct" in text
    assert "only 4.0 GB is free right now; close other programs" in text


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({}, "create hello.py that prints a greeting"),
        ({"main.py": "print(1)\n"}, "explain what this project does"),
    ],
)
def test_the_session_opens_with_a_first_request_that_fits(
    tmp_path: Path, files: dict[str, str], expected: str
) -> None:
    # G-058: the golden J1 ends at a prompt with a suggested first command.
    _git_init(tmp_path)
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    io, said, _ = _io([""], [SERVER])

    wizard.run(tmp_path, interactive=True, io=io, opens_session=True)

    assert said[-1].startswith("Opening the session. Try: ")
    assert expected in said[-1]
