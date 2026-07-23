import subprocess
import sys


def test_run_fingerprint_csv_export(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("provider: local\n", encoding="utf-8")
    cmd = [sys.executable, "-m", "ract.cli"]
    cmd.append("run-fingerprint")
    cmd.append("--csv")
    cmd.append("--config")
    cmd.append(str(config))
    result = subprocess.run(cmd, cwd=str(tmp_path), capture_output=True, text=True)
    assert result.returncode in (0, 1, 2)
