"""Journeys that cannot run as a test yet. Each skip names the card it waits for.

J4 (fix the failing test) waits for the test verifier and the tool loop
(B-010a and B-011a have landed; the verifier is not wired for a fix yet). J5
needs the rewind (B-014c). J3 runs in test_j3_ask_about_the_code.py.
J7 and J9 run in test_j7_resume.py and test_j9_weak_model.py.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(
    reason="J4 blocked: the test verifier for a fix is not wired (B-023 run_tests verifier)"
)
def test_j4_fix_the_failing_test() -> None:
    raise AssertionError("not run")


@pytest.mark.skip(reason="J5 needs B-014c (per-hunk accept, reject and edit)")
def test_j5_rewind() -> None:
    raise AssertionError("not run")
