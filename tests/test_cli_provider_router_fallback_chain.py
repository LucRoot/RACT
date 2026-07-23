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


def test_provider_router_fallback_chain(tmp_path):
    config = tmp_path / "rootact.yaml"
    _write_valid_config(config)
    cmd = [
        sys.executable,
        "-m",
        "rootact.cli",
        "provider",
        "health",
        "--json",
        "--config",
        str(config),
    ]
    result = subprocess.run(cmd, cwd=str(tmp_path), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '"healthy": true' in result.stdout
    assert '"internal": true' in result.stdout
