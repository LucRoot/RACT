__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
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


def test_provider_cost_index_defaults(tmp_path):
    config = tmp_path / "ract.yaml"
    _write_valid_config(config)
    cmd = [
        sys.executable,
        "-m",
        "ract.cli",
        "provider",
        "health",
        "--config",
        str(config),
    ]
    result = subprocess.run(
        cmd,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    assert '"internal": true' in result.stdout
    assert '"healthy": true' in result.stdout
