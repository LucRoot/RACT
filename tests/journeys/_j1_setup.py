"""The first-run scenario J1 uses: a setup reply, a one-step plan, then an answer."""

from __future__ import annotations

import json

from tests.fixtures.fake_model_server import Scenario


def setup_scenario() -> Scenario:
    plan = json.dumps(
        {
            "assumption": "the folder is empty apart from RACT's own files",
            "confidence": 0.9,
            "steps": [
                {
                    "action": "Explain what this folder contains",
                    "provider_hint": "local",
                    "expected_artifact": "",
                }
            ],
        }
    )
    return Scenario.from_dict(
        {
            "model": "fake-coder",
            "turns": [
                {"reply": {"kind": "text", "content": "ready"}},
                {"reply": {"kind": "text", "content": plan}},
                {
                    "reply": {
                        "kind": "text",
                        "content": "The folder holds ract.yaml and prompts/, nothing else yet.",
                    },
                    "repeat": True,
                },
            ],
        }
    )
