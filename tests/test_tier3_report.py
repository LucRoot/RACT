"""B-147 screen half: the `ract doctor --tier3` report as text, at 80, 60 and 40 columns.

Facts in, lines out: the grant (found or not, its signer, expiry and digest start), why tier 3 is
off, the operator key, the unlock window, the sandbox as this machine runs it, the entry-point
record, the session mode, the tools, and the next command for each problem. A control character in
a name is shown escaped.
"""

from __future__ import annotations

import pytest

from ract.ui.tier3_report import GrantFacts, Tier3Facts, tier3_report_lines

WIDTHS = (80, 60, 40)


def _flat(lines: list[str]) -> str:
    return " ".join(" ".join(lines).split())


def _facts(**overrides: object) -> Tier3Facts:
    base: dict[str, object] = {
        "grant": GrantFacts(
            found=True,
            signed_by="operator key 1a2b",
            expires="2027-01-30",
            digest="9f8e7d6c",
        ),
        "why_off": "",
        "key_present": True,
        "key_location": "the user config directory",
        "key_protection": "passphrase, scrypt",
        "window": "off (the grant says sandbox best_effort)",
        "sandbox_backend": "windows-job",
        "sandbox_confines": "nothing, on this machine",
        "sandbox_does_not": "file access outside the project, network",
        "entry_point_record": "pytest.ini recorded at signing",
        "session_mode": "ask",
        "tools_available": ("run_tests",),
        "tools_unavailable": ("run_command",),
        "next_steps": (),
    }
    base.update(overrides)
    return Tier3Facts(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize("width", WIDTHS)
def test_the_report_fits_and_names_the_grant_the_key_and_the_sandbox(
    width: int,
) -> None:
    lines = tier3_report_lines(_facts(), width)
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "found, signed by operator key 1a2b" in text
    assert "expires 2027-01-30" in text
    assert "digest starts 9f8e7d6c" in text
    assert "tier 3 is on for this project" in text
    assert "present, in the user config directory" in text
    assert "backend: windows-job" in text
    assert "does not confine: file access outside the project, network" in text
    assert "session mode: ask" in text


def test_no_grant_says_why_tier_three_is_off_and_how_to_fix_it() -> None:
    facts = _facts(
        grant=GrantFacts(found=False),
        why_off="no grant on file",
        key_present=False,
        next_steps=(("no grant", "ract policy init --guided"),),
    )
    text = _flat(tier3_report_lines(facts, 80))
    assert "none on file" in text
    assert "why tier 3 is off: no grant on file" in text
    assert "not made yet (ract policy keygen makes it at a terminal)" in text
    assert "no grant: run ract policy init --guided" in text


@pytest.mark.parametrize("width", WIDTHS)
def test_next_steps_fit_at_each_width(width: int) -> None:
    facts = _facts(
        next_steps=(
            ("grant expired", "ract policy sign"),
            ("key locked", "/permissions resume"),
        )
    )
    lines = tier3_report_lines(facts, width)
    for line in lines:
        assert len(line) <= width, line


def test_a_control_character_in_a_name_is_shown_escaped() -> None:
    joined = "\n".join(tier3_report_lines(_facts(sandbox_backend="evil\x1b[31m"), 80))
    assert "\x1b" not in joined and "\\x1b" in joined
