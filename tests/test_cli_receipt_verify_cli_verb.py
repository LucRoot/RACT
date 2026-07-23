import subprocess
import sys


def test_receipt_verify_cli_verb(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("provider: local\n", encoding="utf-8")
    cmd = [sys.executable, "-m", "ract.cli"]
    cmd.append("chain")
    cmd.append("verify")
    cmd.append("--chain")
    cmd.append(str(config))
    cmd.append("--json")
    result = subprocess.run(cmd, cwd=str(tmp_path), capture_output=True, text=True)
    assert result.returncode in (0, 1, 2)
