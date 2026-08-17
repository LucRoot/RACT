"""``ract manifest`` restores the v0.1.2-era CHANGELOG verb.

The v0.1.2 CHANGELOG names ``ract manifest`` and ``ract ai-sbom`` as the
two AI provenance manifest verbs. During the v0.4 rebuild the reproducibility
manifest verb was renamed to ``repro-manifest`` and the older name silently
became an unknown positional intent. This test locks the alias so a future
rename cannot drop the historical name again without failing the gate.
"""

from __future__ import annotations

import json
from pathlib import Path


def test_manifest_verb_aliases_repro_manifest(tmp_path: Path) -> None:
    from ract.cli import main

    plan_file = tmp_path / "plan.json"
    config_file = tmp_path / "config.json"
    plan_file.write_text(json.dumps({"steps": ["a", "b"]}), encoding="utf-8")
    config_file.write_text(json.dumps({"model": "internal"}), encoding="utf-8")

    code = main(
        [
            "manifest",
            "--intent",
            "verify alias",
            "--plan",
            str(plan_file),
            "--config",
            str(config_file),
            "--fingerprint",
            "fp-alias",
        ]
    )
    assert code == 0


def test_manifest_verb_listed_in_cli_verbs() -> None:
    from ract.cli import CLI_VERBS

    assert "manifest" in CLI_VERBS
    assert "repro-manifest" in CLI_VERBS
