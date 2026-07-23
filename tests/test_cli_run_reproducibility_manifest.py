__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
import json
import subprocess
import sys
from pathlib import Path


def test_run_reproducibility_manifest(tmp_path):
    plan_path = tmp_path / "plan.json"
    config_path = tmp_path / "config.json"
    plan_path.write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "action": "refactor helper",
                        "provider_hint": "internal",
                        "expected_artifact": "refactored.py",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config_path.write_text(
        json.dumps({"project": {"name": "ract-project"}, "providers": {}}),
        encoding="utf-8",
    )
    cmd = [
        sys.executable,
        "-m",
        "rootact.cli",
        "repro-manifest",
        "--intent",
        "refactor helper",
        "--plan",
        str(plan_path),
        "--config",
        str(config_path),
    ]
    result = subprocess.run(cmd, cwd=str(tmp_path), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '"fingerprint"' in result.stdout
    assert "refactor helper" in result.stdout
