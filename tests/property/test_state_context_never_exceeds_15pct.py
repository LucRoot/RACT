"""v0.5.1 spec-completeness module_02 — property: state_context <= 15%.

Property: for every state_context content string and every shipped
memory-discipline function, after ``seat_state_section`` the
accountant's ``used("state")`` MUST be ``<= floor(0.15 *
input_target)``.

The property complements the boundary-value unit tests in
``tests/unit/test_state_context_15pct_cap.py`` — those pin the
arithmetic; this one pins the invariant across arbitrary content.

Closes audit Lens 1A CRITICAL A-2 via the property lens.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from ract.memory.budget import BudgetAccountant, BudgetDeclaration
from ract.memory.events import NullEventSink
from ract.memory.functions.provider_adapter import (
    _state_cap_tokens,
    seat_state_section,
)


def _declaration(function: str, input_target: int) -> BudgetDeclaration:
    return BudgetDeclaration(
        function=function,
        input_min=100,
        input_target=input_target,
        input_max=input_target + 1000,
        output_min=100,
        output_target=500,
        output_max=500,
        reasoning_headroom=500,
        hard_ceiling=input_target + 1000 + 500 + 500,
    )


_SHIPPED_FUNCTIONS = [
    ("intake", 2000),
    ("research", 3000),
    ("plan", 4000),
    ("edit", 8000),
]


# Hypothesis strategy: newline-separated words. The whitespace token
# estimator counts words separated by any whitespace so newline vs space
# gives the same count; the property doesn't depend on the delimiter
# distribution.
_content_strategy = st.lists(
    st.text(
        alphabet=st.characters(
            min_codepoint=32, max_codepoint=126, blacklist_characters="\n"
        ),
        min_size=1,
        max_size=12,
    ),
    min_size=0,
    max_size=200,
).map(lambda lines: "\n".join(lines))


@given(content=_content_strategy)
def test_state_seated_never_exceeds_15pct_for_intake(content: str) -> None:
    _assert_cap_for("intake", 2000, content)


@given(content=_content_strategy)
def test_state_seated_never_exceeds_15pct_for_research(content: str) -> None:
    _assert_cap_for("research", 3000, content)


@given(content=_content_strategy)
def test_state_seated_never_exceeds_15pct_for_plan(content: str) -> None:
    _assert_cap_for("plan", 4000, content)


@given(content=_content_strategy)
def test_state_seated_never_exceeds_15pct_for_edit(content: str) -> None:
    _assert_cap_for("edit", 8000, content)


def _assert_cap_for(function: str, input_target: int, content: str) -> None:
    """For any content, seated state tokens must be <= floor(0.15 * target).

    The invariant is one-sided: we don't assert that under-cap content
    is untouched (that lives in the boundary-value tests). We assert
    the POST-STATE that the module_02 wire-in guarantees.
    """
    decl = _declaration(function, input_target)
    accountant = BudgetAccountant(declaration=decl)
    sink = NullEventSink()
    cap = _state_cap_tokens(decl)
    section, effective = seat_state_section(
        accountant, content=content, content_hash="test-hash", sink=sink
    )
    assert section.token_count <= cap, (
        f"function={function} target={input_target} cap={cap} "
        f"seated={section.token_count} content_len={len(content)}"
    )
    assert accountant.used("state") == section.token_count
    assert accountant.used("state") <= cap
    # Also: effective content, when passed to the estimator, must not
    # exceed the cap. The prompt the model sees carries the effective
    # content; the accountant's number and the model's number must
    # both live under the cap.
    from ract.memory.functions.provider_adapter import _ESTIMATOR

    assert _ESTIMATOR.estimate(effective) <= cap


# RACT 0.5.1
