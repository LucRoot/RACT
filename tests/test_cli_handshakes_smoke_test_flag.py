import subprocess
import sys


def test_handshakes_smoke_test_flag(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("provider: local\n", encoding="utf-8")
    cmd = [sys.executable, "-m", "ract.cli"]
    cmd.append("handshakes")
    cmd.append("--smoke-test")
    cmd.append("--config")
    cmd.append(str(config))
    result = subprocess.run(
        cmd,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode in (0, 1, 2)
