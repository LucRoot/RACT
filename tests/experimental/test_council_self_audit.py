from ract.experimental.council_self_audit import run_self_audit


def test_run_self_audit_healthy(tmp_path):
    src = tmp_path / "src" / "ract"
    src.mkdir(parents=True)
    (src / "module.py").write_text("def foo(): pass\n", encoding="utf-8")
    result = run_self_audit(tmp_path)
    assert result["healthy"] is True
    assert result["files_checked"] == 1
    assert result["missing_markers"] == []


def test_run_self_audit_ignores_init(tmp_path):
    src = tmp_path / "src" / "ract"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    result = run_self_audit(tmp_path)
    assert result["healthy"] is True
    assert result["files_checked"] == 0


def test_self_audit_html_output(tmp_path):
    import subprocess
    import sys

    src = tmp_path / "src" / "ract"
    src.mkdir(parents=True)
    (src / "module.py").write_text("def foo(): pass\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "self-audit",
            "--project-dir",
            str(tmp_path),
            "--html",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "<!DOCTYPE html>" in result.stdout
    assert "RACT Self-Audit" in result.stdout
    assert "Scanned 1 Python files" in result.stdout
