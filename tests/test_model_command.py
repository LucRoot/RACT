"""B-058: ``/model`` lists the configured models and their facts.

The switch to another provider is not in this card's first part; the
escalation is in the log. These tests cover the listing, the prices, the
trust tag, the key, the widths and the help row.
"""

from __future__ import annotations

from pathlib import Path

from ract import cli
from ract.model_view import model_blocks
from ract.repl import HELP_ROWS, ReplSession
from tests.test_repl import _Console

SENTINEL = "sk-SENTINEL-b058-4410"


def _config(path: Path, *, extra: str = "") -> Path:
    path.write_text(
        "project:\n  name: demo\n"
        "manager_provider: local\n"
        "providers:\n"
        "  local:\n"
        "    adapter: local_http\n"
        "    url: http://127.0.0.1:8010/v1\n"
        "    model: local-7b\n"
        "  cloud:\n"
        "    adapter: openai_compatible\n"
        "    url: https://models.example.invalid/v1\n"
        "    model: cloud-big\n"
        f"    api_key: {SENTINEL}\n"
        "    input_cost_per_1k: 0.0025\n"
        "    output_cost_per_1k: 0.01\n"
        "  second:\n"
        "    adapter: local_http\n"
        "    url: http://127.0.0.1:8011/v1\n"
        "    model: local-14b\n" + extra,
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


# ---------------------------------------------------------------- 1. the blocks


def test_one_block_per_provider_and_the_manager_is_marked(tmp_path: Path) -> None:
    session, console = _session(_config(tmp_path / "ract.yaml"))
    session.handle("/model")
    text = console.text
    assert text.count("adapter: ") == 3
    assert "local (manager, current)" in text
    assert "cloud" in text and "second" in text
    assert "model: cloud-big" in text


# ---------------------------------------------------------------- 2. prices


def test_prices_are_per_million_tokens_with_two_decimals(tmp_path: Path) -> None:
    session, console = _session(_config(tmp_path / "ract.yaml"))
    session.handle("/model")
    assert "price 2.50 in, 10.00 out per 1M tokens" in console.text
    assert "price unknown" in console.text


# ---------------------------------------------------------------- 3. unknown name


def test_an_unknown_name_lists_the_valid_ones_and_changes_nothing(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path / "ract.yaml")
    before = config.read_bytes()
    session, console = _session(config)
    session.handle("/model nosuch")
    assert "valid names: local, cloud, second" in console.text
    assert config.read_bytes() == before


# ---------------------------------------------------------------- 4. no switch yet


def test_naming_a_known_provider_switches_it_for_the_session_and_leaves_the_file(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path / "ract.yaml")
    before = config.read_bytes()
    session, console = _session(config)
    session.handle("/model second")
    assert "manager provider is now 'second' for this session" in console.text
    assert config.read_bytes() == before


# ---------------------------------------------------------------- 5. trust tag


def test_a_repository_named_host_is_tagged_in_the_block(tmp_path: Path) -> None:
    session, console = _session(_config(tmp_path / "ract.yaml"))
    session.handle("/model")
    cloud_line = next(
        line for line in console.lines if "models.example.invalid" in line
    )
    assert "(named by this repository's ract.yaml)" in cloud_line
    local_line = next(line for line in console.lines if "127.0.0.1:8010" in line)
    assert "named by" not in local_line


# ---------------------------------------------------------------- 6. no key


def test_no_key_or_key_fragment_is_printed(tmp_path: Path) -> None:
    session, console = _session(_config(tmp_path / "ract.yaml"))
    session.handle("/model")
    assert SENTINEL not in console.text
    assert SENTINEL[3:20] not in console.text


# ---------------------------------------------------------------- 7. widths


def test_no_line_is_wider_than_the_terminal_at_80_and_60_columns() -> None:
    providers = {
        "a-very-long-provider-name-that-goes-on": {
            "adapter": "openai_compatible",
            "model": "a-model-name-that-is-also-quite-long-indeed",
            "url": "https://a-host-with-a-long-name.example.invalid/v1",
        }
    }
    for width in (80, 60):
        for line in model_blocks(
            providers, "a-very-long-provider-name-that-goes-on", set(), width
        ):
            assert len(line) <= width, line


# ---------------------------------------------------------------- 8. help


def test_help_lists_model() -> None:
    assert any(row[0].startswith("/model") for row in HELP_ROWS)


# ---------------------------------------------------------------- hostile config strings


def test_escape_codes_and_markup_in_names_and_models_are_shown_inert(
    tmp_path: Path,
) -> None:
    import yaml

    evil = "evil\x1b[31m-[bold]x[/bold]\x07"
    config = tmp_path / "ract.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "project": {"name": "demo"},
                "manager_provider": evil,
                "providers": {
                    evil: {
                        "adapter": "local_http\x1b[2J",
                        "url": "http://127.0.0.1:8010/v1",
                        "model": "[red]m[/red]\x07",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    session, console = _session(config)
    session.handle("/model")
    text = console.text
    assert "\x1b" not in text and "\x07" not in text
    assert "[bold]" in text and "[red]" in text  # shown as text, not styled
    session.handle("/model " + evil)


def test_an_unknown_name_with_escape_codes_is_listed_without_them(
    tmp_path: Path,
) -> None:
    session, console = _session(_config(tmp_path / "ract.yaml"))
    session.handle("/model bad\x1b[31mname")
    assert "\x1b" not in console.text
    assert "valid names:" in console.text


def test_userinfo_in_a_url_is_never_shown(tmp_path: Path) -> None:
    config = tmp_path / "ract.yaml"
    config.write_text(
        "project:\n  name: demo\n"
        "manager_provider: local\n"
        "providers:\n"
        "  local:\n"
        "    adapter: local_http\n"
        "    url: http://user:secret@host.example.invalid:1234/v1\n"
        "    model: local-7b\n",
        encoding="utf-8",
    )
    session, console = _session(config)
    session.handle("/model")
    assert "host.example.invalid:1234" in console.text
    assert "user" not in console.text
    assert "secret" not in console.text
