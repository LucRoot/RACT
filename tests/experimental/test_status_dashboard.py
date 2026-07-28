from ract.experimental.status_dashboard import run_status


def test_run_status_healthy(tmp_path):
    (tmp_path / "ract.yaml").write_text("provider: local\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")
    result = run_status(tmp_path)
    assert isinstance(result, dict)
    assert result["healthy"] is True
    assert result["summary"] == "All checks passed"
    assert any(c["name"] == "config_present" and c["passed"] for c in result["checks"])


def test_run_status_unhealthy(tmp_path):
    result = run_status(tmp_path)
    assert isinstance(result, dict)
    assert result["healthy"] is False
    assert result["summary"] == "Some checks failed"
    assert any(
        c["name"] == "config_present" and not c["passed"] for c in result["checks"]
    )


def test_status_markdown_output(tmp_path):
    import subprocess
    import sys

    (tmp_path / "ract.yaml").write_text("provider: local\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "status",
            "--project-dir",
            str(tmp_path),
            "--markdown",
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert "# RACT Status Dashboard" in result.stdout
    assert "| Check | Status | Detail |" in result.stdout
