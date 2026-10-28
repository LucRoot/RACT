"""Journeys that cannot run as a test yet. Each skip names the card it waits for.

J3 (ask about the code, read-only) and J4 (fix the failing test) wait for the
read-only tool loop and the verifier (B-010a, gated). J5 needs the rewind (B-014c).
J7 (resume) and J9 (weak model) are the second batch of B-074.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(
    reason="J3 blocked (B-010a, gated): the read-only tool loop is not built"
)
def test_j3_ask_about_the_code() -> None:
    raise AssertionError("not run")


@pytest.mark.skip(
    reason="J4 blocked (B-010a, gated): the test verifier and tool loop are not built"
)
def test_j4_fix_the_failing_test() -> None:
    raise AssertionError("not run")


@pytest.mark.skip(reason="J5 needs B-014c (rewind)")
def test_j5_rewind() -> None:
    raise AssertionError("not run")


@pytest.mark.skip(
    reason="J7 is batch 2 of B-074 (resume journey); not written in this batch"
)
def test_j7_resume() -> None:
    raise AssertionError("not run")


@pytest.mark.skip(
    reason="J9 is batch 2 of B-074 (weak-model journey); not written in this batch"
)
def test_j9_weak_model() -> None:
    raise AssertionError("not run")
