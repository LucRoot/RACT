import subprocess
import sys


def test_handshakes_smoke_test():
    result = subprocess.run(
        [sys.executable, "-m", "ract.cli", "handshakes", "--smoke-test"],
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0
    assert "smoke ok" in result.stdout
