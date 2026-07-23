__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
import subprocess
import sys
from pathlib import Path

def test_complexity_router_cli_verb(tmp_path):
    config = tmp_path / "rootact.yaml"
    config.write_text(
        """providers:
  local:
    adapter: internal
    command: [python, -c, print(ok)]
""",
        encoding="utf-8",
    )
    cmd = [sys.executable, "-m", "rootact.cli"]
    cmd.append("router")
    cmd.append("select")
    cmd.append("--intent")
    cmd.append("chat")
    cmd.append("--config")
    cmd.append(str(config))
    result = subprocess.run(
        cmd, cwd=str(tmp_path), capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "selected:" in result.stdout


def test_router_select_markdown(tmp_path):
    config = tmp_path / "rootact.yaml"
    config.write_text(
        """providers:
  local:
    adapter: internal
    command: [python, -c, print(ok)]
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "rootact.cli", "router", "select", "--intent", "chat", "--config", str(config), "--markdown"],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "# RACT Router Selection" in result.stdout


def test_router_health_markdown(tmp_path):
    config = tmp_path / "rootact.yaml"
    config.write_text(
        """providers:
  local:
    adapter: internal
    command: [python, -c, print(ok)]
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "rootact.cli", "router", "health", "--config", str(config), "--markdown"],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "# RACT Router Health" in result.stdout

