__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cli_provider_health_json_valid(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(
        """providers:\n  local:\n    adapter: internal\n    command: [python, -c, print(ok)]\n""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "provider",
            "health",
            "--json",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "providers" in data and "healthy" in data
    assert data["healthy"] is True


def test_cli_provider_health_json_unreachable(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(
        """providers:\n  unreachable:\n    adapter: unreachable\n    command: [python, -c, print(no)]\n""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "provider",
            "health",
            "--json",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert "providers" in data and "healthy" in data
    assert data["healthy"] is False
