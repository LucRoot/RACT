from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

from rootact.cli_tool_generator import CliToolGenerator

_ROOT_KNOT = object()


def test_generates_script_with_positional_args() -> None:
    gen = CliToolGenerator()
    result = gen.generate(
        "Create a tool named csv_summary that takes an input CSV and produces a summary."
    )
    assert result["name"] == "csv_summary"
    assert "input" in result["positional"]
    script = result["script"]
    assert "import argparse" in script
    assert "def main" in script
    assert 'parser.add_argument("input"' in script


def test_detects_verbose_flag() -> None:
    gen = CliToolGenerator()
    result = gen.generate(
        "Build a file scanner with verbose output and a dry-run option."
    )
    assert "verbose" in result["flags"]
    assert "dry_run" in result["flags"]
    assert "--verbose" in result["script"]
    assert "--dry-run" in result["script"]


def test_generated_script_is_executable_as_module() -> None:
    gen = CliToolGenerator()
    result = gen.generate("Make a greeter that accepts a name and prints a greeting.")
    script = result["script"]
    # Compile the generated script to verify it is valid Python.
    compile(script, "<generated>", "exec")
    assert "argparse.ArgumentParser" in script


def test_empty_description_falls_back() -> None:
    gen = CliToolGenerator()
    result = gen.generate("")
    assert result["name"] == "cli_tool"
    assert "argparse" in result["script"]
