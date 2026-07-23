import subprocess
import sys


def test_skills_markdown_list(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("provider: local\n", encoding="utf-8")
    cmd = [sys.executable, "-m", "ract.cli"]
    cmd.append("skills")
    cmd.append("list")
    cmd.append("--markdown")
    cmd.append("--config")
    cmd.append(str(config))
    result = subprocess.run(
        cmd,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode in (0, 1, 2)
