"""module_09: three new CLI verbs resolve through --help.

- ``ract memory init``
- ``ract memory apply-narrowings``
- ``ract retrieval query``

Each verb should exit non-zero on --help (argparse convention) and
print its usage line without raising an unrelated traceback. A smoke
``memory init`` against an empty tmp repo completes with exit 0.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=60,
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["memory", "init", "--help"],
        ["memory", "apply-narrowings", "--help"],
        ["retrieval", "query", "--help"],
    ],
)
def test_help_resolves(argv: list[str]) -> None:
    """--help renders the usage line for each new verb."""
    result = _run_cli(argv)
    combined = (result.stdout + result.stderr).lower()
    # argparse --help exits 0 with usage on stdout.
    assert result.returncode == 0, combined
    assert "usage:" in combined


def test_memory_init_smoke(tmp_path: Path) -> None:
    """`ract memory init` against a bare tmp dir completes cleanly."""
    (tmp_path / "seed.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    result = _run_cli(["memory", "init", str(tmp_path), "--skip-semantic"])
    # Skip-semantic keeps the smoke offline-safe. LSP-based graph
    # build may warn (non-fatal); the return code is 0 as long as
    # the symbol index writes.
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    db_path = tmp_path / ".ract" / "memory" / "symbols.db"
    assert db_path.is_file(), f"symbol index missing at {db_path}\n{combined}"


def test_memory_verb_registered_in_cli_verbs() -> None:
    """CLI_VERBS carries the new 'memory' verb."""
    from ract.cli import CLI_VERBS

    assert "memory" in CLI_VERBS


# RACT 0.5.0
