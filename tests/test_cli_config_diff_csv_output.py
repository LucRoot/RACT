import subprocess
import sys


def test_config_diff_csv_output(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("provider: local\n", encoding="utf-8")
    cmd = [sys.executable, "-m", "ract.cli"]
    cmd.append("config")
    cmd.append("diff")
    cmd.append("--csv")
    cmd.append("--config")
    cmd.append(str(config))
    result = subprocess.run(cmd, cwd=str(tmp_path), capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.strip() == "change_type,key,before,after"
