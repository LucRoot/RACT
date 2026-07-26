"""WhispererContract runs pre-plan; the planner prompt carries the brief."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ract.contracts.whisperer import DialectBrief, WhispererContract


def test_dialect_brief_injected_into_planner_prompt() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "module_a.py").write_text("import os\nfrom pathlib import Path\n")
        (ws / "module_b.py").write_text("from module_a import Path\n")
        contract = WhispererContract(ws)
        original_prompt = "please refactor the loader"
        injected = contract.inject_into_prompt(original_prompt, snapshot_id="s1")
        assert original_prompt in injected
        assert "Codebase dialect brief" in injected
        assert injected.index("Codebase dialect brief") < injected.index(
            original_prompt
        )


def test_dialect_brief_is_cached_per_snapshot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        contract = WhispererContract(Path(tmp))
        a = contract.build("snap-1")
        b = contract.build("snap-1")
        assert a is b, "same snapshot_id must return the cached DialectBrief"


def test_dialect_brief_shape_is_structured() -> None:
    brief = DialectBrief(
        workspace_snapshot_id="s",
        naming_conventions=("snake_case for functions",),
        forbidden_idioms=("bare except",),
    )
    prefix = brief.to_prompt_prefix()
    assert "snake_case" in prefix
    assert "bare except" in prefix
    assert prefix.startswith("## Codebase dialect brief")


# RACT 0.4.0
