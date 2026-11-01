"""B-172 slice 1 (WRIGHT, ADR-0049 D1, D2): roles as data.

The loader (ract.roles.loader) and the six role files do not exist yet, so these tests fail first.
The golden tests pin the prompt text the product sends today (the reviewer and the planner), so that
moving the prompts into data changes nothing a model sees.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.roles import loader

GOLDEN = Path(__file__).parent / "golden"
ROLE_NAMES = ["intake", "explorer", "planner", "editor", "verifier", "reviewer"]
D2_KEYS = {
    "purpose",
    "input",
    "output",
    "tools",
    "budget",
    "model_class",
    "prompt",
    "checklist",
    "stop",
    "failure_modes",
}


def _minimal_role(extra: str = "", drop: str = "") -> str:
    lines = [
        "purpose: Read the code and answer.",
        "input: ResearchQuestion",
        "output: ResearchBundle",
        "tools: [read_file, list_dir, glob, grep]",
        "budget: explorer",
        "model_class: either",
        "prompt: explorer.v1",
        "checklist: [every cited file exists]",
        "stop: an answer that passes the checklist",
        "failure_modes: [retry with the error]",
    ]
    lines = [line for line in lines if not line.startswith(drop + ":")] if drop else lines
    return "\n".join(lines) + ("\n" + extra if extra else "") + "\n"


def test_the_six_built_in_roles_load_from_the_package() -> None:
    roles = loader.load_builtin_roles()
    assert sorted(roles) == sorted(ROLE_NAMES)


def test_each_role_carries_every_d2_key() -> None:
    for name, role in loader.load_builtin_roles().items():
        assert D2_KEYS <= set(role.data), f"{name} is missing {sorted(D2_KEYS - set(role.data))}"


def test_the_verifier_is_not_a_model_role() -> None:
    assert loader.load_builtin_roles()["verifier"].data["model_class"] == "none"


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(loader.RoleError, match="surprise"):
        loader.parse_role(_minimal_role(extra="surprise: 1"), name="explorer")


def test_a_missing_field_is_refused() -> None:
    with pytest.raises(loader.RoleError, match="stop"):
        loader.parse_role(_minimal_role(drop="stop"), name="explorer")


def test_a_huge_file_is_refused() -> None:
    with pytest.raises(loader.RoleError, match="size"):
        loader.parse_role("purpose: " + "x" * (loader.MAX_BYTES + 1), name="explorer")


def test_the_reviewer_prompt_is_unchanged() -> None:
    from ract.review import reviewer

    golden = (GOLDEN / "reviewer_prompt.txt").read_text(encoding="utf-8")
    assert reviewer.prompt() == golden


def test_the_planner_prompt_is_unchanged(tmp_path: Path) -> None:
    from ract.loop_planner import LoopPlanner

    planner = LoopPlanner(tmp_path / "ract.yaml")
    golden = (GOLDEN / "planner_prompt.txt").read_text(encoding="utf-8")
    assert planner._planner_prompt("make the tests pass") == golden
