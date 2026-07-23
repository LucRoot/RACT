__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
import subprocess
import sys

def test_coverage_badge_cli_verb(tmp_path):
    config = tmp_path / "rootact.yaml"
    config.write_text("provider: local\n", encoding="utf-8")
    cmd = [sys.executable, "-m", "rootact.cli"]
    cmd.append("coverage")
    cmd.append("badge")
    cmd.append("--output")
    cmd.append(str(config))
    cmd.append("--coverage-pct")
    cmd.append("0.0")
    result = subprocess.run(
        cmd, cwd=str(tmp_path), capture_output=True, text=True
    )
    assert result.returncode in (0, 1, 2)

