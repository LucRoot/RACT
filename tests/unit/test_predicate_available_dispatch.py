"""Unit -- AcceptancePredicate.available dispatch + gates helper.

v0.5.1 spec-completeness module_07 (Lens 2 Delta 2 companion).
Locks the per-invocation availability check in isolation. Wire
tests live at ``tests/integration/test_verifier_availability_precheck.py``.
"""

from __future__ import annotations

import shutil


from ract.core.gates import check_invocation_available
from ract.core.predicate import (
    AcceptancePredicate,
    ArtifactInvocation,
    AssertionInvocation,
    HypothesisInvocation,
    MypyInvocation,
    PytestInvocation,
    RelatedFileCoverageInvocation,
    new_predicate_id,
)


def _identity(ws) -> bool:
    return True


class TestArtifactAlwaysAvailable:
    def test_artifact_invocation_always_available(self) -> None:
        avail, reason = check_invocation_available(ArtifactInvocation(path="x.txt"))
        assert avail is True
        assert reason == ""

    def test_related_file_coverage_always_available(self) -> None:
        avail, reason = check_invocation_available(
            RelatedFileCoverageInvocation(
                source_glob="src/**/*.py",
                must_also_touch_glob="tests/**/*.py",
            )
        )
        assert avail is True
        assert reason == ""


class TestAssertionInvocationAvailability:
    def test_healthy_callable_is_available(self) -> None:
        avail, reason = check_invocation_available(
            AssertionInvocation(
                callable_ref="tests.unit.test_predicate_available_dispatch:_identity"
            )
        )
        assert avail is True
        assert reason == ""

    def test_unimportable_module_is_unavailable(self) -> None:
        avail, reason = check_invocation_available(
            AssertionInvocation(callable_ref="nonexistent.foo.bar:fn")
        )
        assert avail is False
        assert "nonexistent" in reason
        assert "callable_ref" in reason

    def test_missing_attribute_is_unavailable(self) -> None:
        avail, reason = check_invocation_available(
            AssertionInvocation(
                callable_ref="tests.unit.test_predicate_available_dispatch:NOT_A_REAL_NAME"
            )
        )
        assert avail is False
        assert "NOT_A_REAL_NAME" in reason

    def test_malformed_ref_is_unavailable(self) -> None:
        # Bare ref (no dots, no colon) — _resolve_callable raises ValueError.
        avail, reason = check_invocation_available(
            AssertionInvocation(callable_ref="bareword")
        )
        assert avail is False


class TestBinaryBasedAvailability:
    def test_pytest_available_when_binary_on_path(self) -> None:
        # Dev env has pytest installed (per pyproject.toml dev deps).
        avail, reason = check_invocation_available(
            PytestInvocation(selector="tests/x.py::t")
        )
        # We only assert the mapping semantic: if binary present, avail=True.
        if shutil.which("pytest") is not None:
            assert avail is True
            assert reason == ""
        else:
            assert avail is False
            assert "pytest" in reason

    def test_mypy_available_when_binary_on_path(self) -> None:
        avail, reason = check_invocation_available(MypyInvocation(target="src/ract"))
        if shutil.which("mypy") is not None:
            assert avail is True
            assert reason == ""
        else:
            assert avail is False
            assert "mypy" in reason

    def test_hypothesis_available_when_importable(self) -> None:
        avail, reason = check_invocation_available(
            HypothesisInvocation(target="ract.x:roundtrip")
        )
        # hypothesis is a dev dep; should be importable in the test env.
        assert avail is True, (
            f"hypothesis must be importable in the dev test env; got reason={reason!r}"
        )


class TestPredicateAvailableProxy:
    def test_predicate_available_delegates_to_gates(self) -> None:
        pred = AcceptancePredicate(
            id=new_predicate_id(),
            kind="artifact",
            invocation=ArtifactInvocation(path="x.txt"),
        )
        avail, reason = pred.available()
        assert avail is True
        assert reason == ""

    def test_predicate_available_reports_bad_callable(self) -> None:
        pred = AcceptancePredicate(
            id=new_predicate_id(),
            kind="invariant",
            invocation=AssertionInvocation(callable_ref="bad.module:fn"),
        )
        avail, reason = pred.available()
        assert avail is False
        assert "bad" in reason


# RACT 0.5.1
