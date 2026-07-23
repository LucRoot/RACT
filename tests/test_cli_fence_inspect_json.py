__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cli_fence_inspect_json_with_annotation(tmp_path):
    config = tmp_path / "rootact.yaml"
    config.write_text(
        """providers:
  local:
    adapter: internal
    command: [python, -c, print(ok)]
""",
        encoding="utf-8",
    )
    file = tmp_path / "annotated_file.py"
    file.write_text(
        """# load-bearing: <reason>
def class_block():
    pass
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "fence",
            "inspect",
            "--file",
            str(file),
            "--json",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "file" in data and "regions" in data
    assert "reason" in data["regions"][0]


def test_cli_fence_inspect_json_clean_file(tmp_path):
    config = tmp_path / "rootact.yaml"
    config.write_text(
        """providers:
  local:
    adapter: internal
    command: [python, -c, print(ok)]
""",
        encoding="utf-8",
    )
    file = tmp_path / "clean_file.py"
    file.write_text(
        """def class_block():
    pass
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "fence",
            "inspect",
            "--file",
            str(file),
            "--json",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "file" in data and "regions" in data
    assert len(data["regions"]) == 0


def test_cli_fence_inspect_csv_with_annotation(tmp_path):
    config = tmp_path / "rootact.yaml"
    config.write_text(
        """providers:
  local:
    adapter: internal
    command: [python, -c, print(ok)]
""",
        encoding="utf-8",
    )
    file = tmp_path / "annotated_file.py"
    file.write_text(
        """# load-bearing: <reason>
def class_block():
    pass
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "fence",
            "inspect",
            "--file",
            str(file),
            "--csv",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "file,start_line,end_line,reason,annotation_line"
    assert len(lines) == 2
