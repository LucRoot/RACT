"""B-220: every verb's help example parses, and the help text is true.

``ract whisper "..."`` failed with "arguments are required: --intent" and
``ract refactor <target>`` needed ``--old`` and ``--new``. Each example is run
through the real dispatcher with argument parsing allowed to finish and the
command stopped right after, so nothing runs; a parse failure exits 2.
"""

from __future__ import annotations

import argparse
import shlex
from pathlib import Path

import pytest

from ract import cli
from ract.cli_examples import VERB_EXAMPLES


class _Parsed(Exception):
    """Raised right after a successful parse, so the example does no work."""


@pytest.mark.parametrize("verb", sorted(VERB_EXAMPLES))
def test_the_example_parses(
    verb: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = VERB_EXAMPLES[verb]
    if "<" in example:
        example = (
            example.replace("<events.jsonl>", "events.jsonl")
            .replace("<", "")
            .replace(">", "")
        )
    argv = shlex.split(example)[1:]
    real_parse = argparse.ArgumentParser.parse_args
    real_known = argparse.ArgumentParser.parse_known_args

    def parse_args(self, args=None, namespace=None):  # type: ignore[no-untyped-def]
        real_parse(self, args, namespace)
        raise _Parsed

    def parse_known_args(self, args=None, namespace=None):  # type: ignore[no-untyped-def]
        result = real_known(self, args, namespace)
        if self.prog.startswith("ract ") and self.prog != "ract":
            raise _Parsed
        return result

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RACT_NO_NETWORK", "1")
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", parse_args)
    monkeypatch.setattr(argparse.ArgumentParser, "parse_known_args", parse_known_args)
    try:
        cli.main(argv)
    except _Parsed:
        return
    except SystemExit as exc:
        assert exc.code != 2, f"{example!r} did not parse"


def test_the_bare_help_names_the_global_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ract.cli_help import print_discovery_help

    print_discovery_help(cli.CLI_VERBS)
    text = capsys.readouterr().out
    for flag in ("--print", "--no-color", "--plain", "--no-network"):
        assert flag in text, flag


def test_trace_takes_a_run_id_or_an_events_file(tmp_path: Path) -> None:
    from ract.trace.cli_trace import _run_events_path

    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    assert _run_events_path(Path("evals/runs"), str(events)) == events
    assert _run_events_path(Path("evals/runs"), str(tmp_path)) == events
    assert _run_events_path(Path("evals/runs"), "r1") == Path(
        "evals/runs/r1/events.jsonl"
    )
