"""B-111: the tier-3 status line and the expiry notice, in every state (ADR-0048 D3).

Pure text: no terminal, no key, no policy file. Each state is checked at 40 columns,
in plain text, and with the rich markup that marks the two states that must not be
missed. Nothing may carry an escape sequence.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from ract.ui.tier_status_view import TierState, expiry_notice, status_line

TODAY = date(2026, 10, 30)


@pytest.mark.parametrize(
    ("state", "today", "text"),
    [
        (TierState(), TODAY, "T3 off (no grant)"),
        (TierState(mode="ask"), TODAY, "T3 ask"),
        (TierState(mode="allowlist"), TODAY, "T3 allowlist"),
        (
            TierState(mode="unrestricted", grant_expires=date(2027, 1, 1)),
            TODAY,
            "UNRESTRICTED (signed grant)",
        ),
        (TierState(mode="ask", suspended=True), TODAY, "T3 suspended: policy changed"),
        (
            TierState(grant_expires=date(2026, 12, 1)),
            date(2026, 12, 2),
            "T3 off (grant expired 2026-12-01)",
        ),
    ],
)
def test_each_state_has_its_adr_wording(
    state: TierState, today: date, text: str
) -> None:
    assert status_line(state, today) == text
    assert len(text) <= 40


def test_rich_markup_only_for_the_states_that_must_not_be_missed() -> None:
    loud = TierState(mode="unrestricted", grant_expires=date(2027, 1, 1))
    quiet = TierState(mode="ask")
    assert (
        status_line(loud, TODAY, rich=True)
        == "[bold]UNRESTRICTED (signed grant)[/bold]"
    )
    assert status_line(
        TierState(mode="ask", suspended=True), TODAY, rich=True
    ).startswith("[bold]")
    assert status_line(quiet, TODAY, rich=True) == "T3 ask"


@pytest.mark.parametrize(
    "state",
    [
        TierState(),
        TierState(mode="ask"),
        TierState(mode="unrestricted", grant_expires=date(2027, 1, 1)),
        TierState(mode="ask", suspended=True),
    ],
)
def test_no_escape_sequence_in_plain_or_rich_text(state: TierState) -> None:
    for rich in (False, True):
        assert "\x1b" not in status_line(state, TODAY, rich=rich)


@pytest.mark.parametrize(
    ("days", "words"),
    [
        (8, None),
        (7, "in 7 days"),
        (1, "tomorrow"),
        (0, "today"),
        (-1, None),
    ],
)
def test_the_expiry_notice_is_raised_inside_seven_days_only(
    days: int, words: str | None
) -> None:
    state = TierState(mode="ask", grant_expires=TODAY + timedelta(days=days))
    notice = expiry_notice(state, TODAY)
    if words is None:
        assert notice is None
    else:
        assert notice is not None and words in notice and "sign it again" in notice


def test_no_grant_no_notice() -> None:
    assert expiry_notice(TierState(), TODAY) is None
