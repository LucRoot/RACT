import subprocess
import sys
from pathlib import Path


def _write_valid_config(path: Path) -> None:
    path.write_text(
        "providers:\n"
        "  internal:\n"
        "    adapter: internal\n"
        "    command:\n"
        "      - echo\n"
        "      - hello\n",
        encoding="utf-8",
    )


def test_router_dry_run_mode(tmp_path):
    config = tmp_path / "ract.yaml"
    _write_valid_config(config)
    cmd = [
        sys.executable,
        "-m",
        "ract.cli",
        "router",
        "select",
        "--intent",
        "dry-run intent",
        "--json",
        "--config",
        str(config),
    ]
    result = subprocess.run(cmd, cwd=str(tmp_path), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '"selected":' in result.stdout
    assert '"internal"' in result.stdout
