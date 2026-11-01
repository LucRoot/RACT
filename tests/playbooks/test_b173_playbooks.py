"""B-173 slice 1 (WRIGHT, ADR-0049 D7): playbooks as data.

The loader (ract.playbooks.loader) and the two playbook files do not exist yet, so these tests fail
first. A playbook names roles from B-172 and the tools a grant allows. Its acceptance checks are
proposals: the loader stores them as text and never runs them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.playbooks import loader

PLAYBOOK_NAMES = ["explain_code", "fix_failing_test"]
REQUIRED_KEYS = {"name", "purpose", "roles", "acceptance", "stop", "asks"}


def _minimal(extra: str = "", drop: str = "") -> str:
    lines = [
        "name: explain_code",
        "purpose: Explain how a part of the code works.",
        "roles:",
        "  - intake",
        "  - explorer",
        "acceptance:",
        "  - every cited path and line exists",
        "stop: the explorer answer passes the acceptance checks",
        "asks:",
        "  - the question to answer",
    ]
    lines = [line for line in lines if not line.startswith(drop + ":")] if drop else lines
    return "\n".join(lines) + ("\n" + extra if extra else "") + "\n"


def test_the_two_built_in_playbooks_load() -> None:
    playbooks = loader.load_builtin_playbooks()
    assert sorted(playbooks) == sorted(PLAYBOOK_NAMES)


def test_each_playbook_carries_every_key() -> None:
    for name, playbook in loader.load_builtin_playbooks().items():
        assert REQUIRED_KEYS <= set(playbook.data), f"{name} is missing {sorted(REQUIRED_KEYS - set(playbook.data))}"


def test_explain_code_needs_only_intake_and_explorer() -> None:
    playbook = loader.load_builtin_playbooks()["explain_code"]
    assert playbook.data["roles"] == ["intake", "explorer"]


def test_roles_keep_their_order() -> None:
    playbook = loader.load_builtin_playbooks()["fix_failing_test"]
    roles = playbook.data["roles"]
    assert roles.index("planner") < roles.index("editor") < roles.index("verifier")


def test_acceptance_checks_are_text_and_not_run(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    text = _minimal().replace(
        "  - every cited path and line exists",
        f"  - every cited path and line exists\n  - touch {marker}",
    )
    playbook = loader.parse_playbook(text, name="explain_code")
    assert marker.exists() is False
    assert any("touch" in item for item in playbook.data["acceptance"])


def test_an_unknown_role_is_refused() -> None:
    with pytest.raises(loader.PlaybookError, match="unknown role"):
        loader.parse_playbook(_minimal().replace("  - explorer", "  - wizard"), name="explain_code")


def test_a_role_needing_a_tool_the_grant_lacks_is_refused() -> None:
    # The explorer needs read_file. A grant with no tools must refuse it, and name the tool.
    with pytest.raises(loader.PlaybookError, match="read_file"):
        loader.parse_playbook(_minimal(), name="explain_code", grant_tools=frozenset())


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(loader.PlaybookError, match="surprise"):
        loader.parse_playbook(_minimal(extra="surprise: 1"), name="explain_code")


def test_a_missing_field_is_refused() -> None:
    with pytest.raises(loader.PlaybookError, match="stop"):
        loader.parse_playbook(_minimal(drop="stop"), name="explain_code")


def test_a_huge_file_is_refused() -> None:
    with pytest.raises(loader.PlaybookError, match="size"):
        loader.parse_playbook("purpose: " + "x" * (loader.MAX_BYTES + 1), name="explain_code")


@pytest.mark.parametrize("bad", ["../x", ".hidden", "a/b", ""])
def test_a_hostile_name_is_refused(bad: str) -> None:
    with pytest.raises(loader.PlaybookError):
        loader.parse_playbook(_minimal(), name=bad)
