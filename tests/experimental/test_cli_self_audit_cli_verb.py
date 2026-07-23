__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
import json
import subprocess
import sys


def test_self_audit_cli_verb(tmp_path):
    config = tmp_path / "rootact.yaml"
    config.write_text("provider: local\n", encoding="utf-8")
    cmd = [
        sys.executable,
        "-m",
        "rootact.cli",
        "self-audit",
        "--json",
        "--config",
        str(config),
    ]
    result = subprocess.run(
        cmd,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["healthy"] is True
    assert "files_checked" in report
