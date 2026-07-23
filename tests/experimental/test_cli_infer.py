# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys
from pathlib import Path



def _write_config(path: Path) -> None:
    path.write_text(
        """
inference_router:
  tiers:
    local:
      endpoints:
        - name: qwen
          base_url: http://127.0.0.1:8106
          model: qwen
      cost: 1
    low_cost_cloud:
      endpoints:
        - name: cloud
          base_url: http://cloud.example.com
          model: cheap
      cost: 5
    high_cost_fallback:
      endpoints:
        - name: frontier
          base_url: http://frontier.example.com
          model: big
      cost: 50
  thresholds:
    low: 0.30
    medium: 0.55
    high: 0.80
  cross_tier_fallback: true
""",
        encoding="utf-8",
    )


def test_infer_routes_trivial_task_to_local(tmp_path: Path):
    config = tmp_path / "rootact.yaml"
    _write_config(config)
    cmd = [
        sys.executable,
        "-m",
        "rootact.cli",
        "infer",
        "fix typo in README",
        "--config",
        str(config),
        "--json",
    ]
    result = subprocess.run(
        cmd,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["selected_tier"] == "local"
    assert data["selected_endpoint"] == "qwen"


def test_infer_routes_frontier_task_to_fallback(tmp_path: Path):
    config = tmp_path / "rootact.yaml"
    _write_config(config)
    cmd = [
        sys.executable,
        "-m",
        "rootact.cli",
        "infer",
        "Design a repo-wide architecture refactor for unknown frontier algorithms",
        "--config",
        str(config),
        "--json",
    ]
    result = subprocess.run(
        cmd,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["selected_tier"] == "high_cost_fallback"
    assert data["selected_endpoint"] == "frontier"


def test_infer_missing_config(tmp_path: Path):
    cmd = [
        sys.executable,
        "-m",
        "rootact.cli",
        "infer",
        "fix typo",
        "--config",
        str(tmp_path / "missing.yaml"),
    ]
    result = subprocess.run(
        cmd,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 1
    assert "config not found" in result.stderr


def test_infer_config_without_router_section(tmp_path: Path):
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    cmd = [
        sys.executable,
        "-m",
        "rootact.cli",
        "infer",
        "fix typo",
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
    assert result.returncode == 1
    assert "inference_router" in result.stderr


def test_infer_markdown_output(tmp_path: Path):
    config = tmp_path / "rootact.yaml"
    _write_config(config)
    cmd = [
        sys.executable,
        "-m",
        "rootact.cli",
        "infer",
        "fix typo",
        "--config",
        str(config),
        "--markdown",
    ]
    result = subprocess.run(
        cmd,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    assert "# RACT Inference Router Selection" in result.stdout
    assert "local" in result.stdout
