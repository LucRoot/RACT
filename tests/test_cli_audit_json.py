import json
import subprocess
import sys


def test_cli_audit_json_passes_on_healthy_project(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(
        "project:\n"
        "  name: audit-test\n"
        "manager_provider: local\n"
        "providers:\n"
        "  local:\n"
        "    adapter: local_http\n"
        "    base_url: http://127.0.0.1:8011/v1\n"
        "    model: local\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "audit",
            "--config",
            str(config),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "passed" in data
    assert "total" in data
    assert "findings" in data
    assert data["passed"] == data["total"]
