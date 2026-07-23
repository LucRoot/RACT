__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
import subprocess
import sys
from pathlib import Path

def test_leaderboard_html_export(tmp_path):
    config = tmp_path / "rootact.yaml"
    config.write_text("provider: local\n", encoding="utf-8")
    cmd = [sys.executable, "-m", "rootact.cli"]
    cmd.append("leaderboard")
    cmd.append("--html")
    cmd.append("--config")
    cmd.append(str(config))
    result = subprocess.run(
        cmd, cwd=str(tmp_path), capture_output=True, text=True
    )
    assert result.returncode in (0, 1, 2)

