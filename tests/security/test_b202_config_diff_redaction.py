"""B-202 (part 3): `ract config diff` prints no literal key, the way setup's diff does.

``ract config diff`` flattened both ract.yaml files and printed the raw
added/removed/changed values to stdout; a literal ``api_key`` in ract.yaml,
an explicitly supported configuration, reached CI logs in cleartext. Setup's
reconfigure diff masked the same value (B-202); this verb now uses the same
mechanism. The keys here are throwaway values, built in pieces so this file
does not itself trip the egress scan.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ract import redaction
from ract.cli import _config_command

KEY = "sk-proj-" + "G3P3" * 8
NO_SHAPE = "zz" + "7Kp9Qm2Lw4Vx8Ns3Tr6Hy"

BASELINE = """\
providers:
  cloud:
    adapter: openai
    url: https://api.openai.com/v1
    model: gpt-4o-mini
"""
CURRENT = """\
providers:
  cloud:
    adapter: openai
    url: https://api.openai.com/v1
    model: gpt-4o
    api_key: {key}
  lab:
    adapter: openai
    url: https://api.openai.com/v1
    model: gpt-4o-mini
    api_key: {no_shape}
"""


def _write_pair(tmp_path: Path) -> tuple[Path, Path]:
    baseline = tmp_path / "baseline.yaml"
    baseline.write_text(BASELINE, encoding="utf-8")
    config = tmp_path / "ract.yaml"
    config.write_text(CURRENT.format(key=KEY, no_shape=NO_SHAPE), encoding="utf-8")
    return baseline, config


def test_default_output_masks_literal_keys_and_keeps_plain_values(
    tmp_path: Path, capsys: object
) -> None:
    baseline, config = _write_pair(tmp_path)
    try:
        code = _config_command(
            ["diff", "--config", str(config), "--baseline", str(baseline)]
        )
    finally:
        redaction.clear_known()
    assert code == 0
    out = capsys.readouterr().out  # type: ignore[union-attr]
    assert KEY not in out
    assert NO_SHAPE not in out
    assert "gpt-4o-mini" in out  # a non-secret changed value still prints
    assert '"after": "gpt-4o"' in out


def test_json_output_masks_literal_keys_and_keeps_plain_values(
    tmp_path: Path, capsys: object
) -> None:
    baseline, config = _write_pair(tmp_path)
    try:
        code = _config_command(
            ["diff", "--json", "--config", str(config), "--baseline", str(baseline)]
        )
    finally:
        redaction.clear_known()
    assert code == 0
    out = capsys.readouterr().out  # type: ignore[union-attr]
    assert KEY not in out
    assert NO_SHAPE not in out
    report = json.loads(out)
    assert report["added"]["providers.cloud.api_key"] == "[redacted]"
    assert report["added"]["providers.lab.api_key"] == "[redacted]"
    assert report["changed"]["providers.cloud.model"] == {
        "before": "gpt-4o-mini",
        "after": "gpt-4o",
    }


def test_the_cli_masks_a_literal_key_end_to_end(tmp_path: Path) -> None:
    baseline, config = _write_pair(tmp_path)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    env.update(NO_COLOR="1", RACT_NO_NETWORK="1")
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "config",
            "diff",
            "--json",
            "--config",
            "ract.yaml",
            "--baseline",
            "baseline.yaml",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
    )
    assert done.returncode == 0
    assert KEY not in done.stdout + done.stderr
    assert NO_SHAPE not in done.stdout + done.stderr
    assert "gpt-4o" in done.stdout
