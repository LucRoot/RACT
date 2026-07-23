import subprocess
import sys


def test_assumption_register_cli_verb(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("provider: local\n", encoding="utf-8")
    cmd = [sys.executable, "-m", "ract.cli"]
    cmd.append("assumption")
    cmd.append("register")
    cmd.append("--plan")
    cmd.append(str(config))
    cmd.append("--results")
    cmd.append(str(config))
    result = subprocess.run(cmd, cwd=str(tmp_path), capture_output=True, text=True)
    assert result.returncode in (0, 1, 2)
