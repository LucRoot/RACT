"""B-091 (D-091): a scripted answer may not know more than the fixture repository does.

The fake model answers from its scenario. ``ask_calc_answer`` once said that ``add()`` returns
``a + b`` while the fixture repository has ``return a - b``; a real model reading that file
could not give that answer. This test reads the fixture's ``add()`` and fails when a scenario
that answers about it states a behaviour the fixture does not have.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.ux.run_baseline import CALC_FILES

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "tests" / "fixtures" / "scenarios" / "ask_calc_answer.json"


def _fixture_add_operator() -> str:
    body = CALC_FILES["src/calc.py"]
    match = re.search(r"def add\(a, b\):\s*\n\s*return a (\S) b", body)
    assert match, "the fixture's add() has a shape this test does not read"
    return match.group(1)


def _scripted_final_answers() -> list[str]:
    data = json.loads(SCENARIO.read_text(encoding="utf-8"))
    return [
        turn["reply"]["envelope"]["final"]
        for turn in data["turns"]
        if "envelope" in turn.get("reply", {})
    ]


def test_the_scripted_answer_states_the_fixture_behaviour():
    operator = _fixture_add_operator()
    finals = _scripted_final_answers()
    assert finals, "the scenario must script an answer"
    for final in finals:
        if operator == "-":
            # The fixture subtracts. An answer that says the sum is the current behaviour is ahead of it.
            assert "returns a - b" in final, final
            assert "returns a + b" not in final, final
        else:
            assert f"a {operator} b" in final, final


def test_a_scripted_answer_better_than_the_fixture_fails():
    # Guard the guard: a sum-claiming answer must be rejected against this fixture.
    assert _fixture_add_operator() == "-"
    bad = "add(a, b) in src/calc.py returns a + b: the sum of its two arguments."
    assert "returns a - b" not in bad
