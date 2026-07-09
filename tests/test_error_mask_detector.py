# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the error-mask detector."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.error_mask_detector import ErrorMaskDetector, error_mask_violations


def test_detects_bare_except():
    source = """
try:
    risky()
except:
    pass
"""
    violations = error_mask_violations(source)
    assert any(v["rule"] == "bare-except" for v in violations)


def test_detects_except_exception_pass():
    source = """
try:
    risky()
except Exception:
    pass
"""
    violations = error_mask_violations(source)
    assert any(v["rule"] == "except-pass" for v in violations)


def test_detects_except_runtime_error_return_none():
    source = """
try:
    risky()
except RuntimeError:
    return None
"""
    violations = error_mask_violations(source)
    assert any(v["rule"] == "except-return-none" for v in violations)


def test_detects_logging_only_handler():
    source = """
try:
    risky()
except Exception:
    logger.warning("something went wrong")
"""
    violations = error_mask_violations(source)
    assert any(v["rule"] == "except-log-no-recovery" for v in violations)


def test_permits_accountability_comment():
    source = """
try:
    risky()
# error-mask-permitted: cause=shutdown race recovery=graceful degradation
except Exception:
    pass
"""
    violations = error_mask_violations(source)
    assert not any(v["rule"] == "except-pass" for v in violations)


def test_detects_contextlib_suppress_broad():
    source = """
import contextlib

with contextlib.suppress(Exception):
    risky()
"""
    violations = error_mask_violations(source)
    assert any(v["rule"] == "contextlib-suppress-broad" for v in violations)


def test_ignores_contextlib_suppress_narrow():
    source = """
import contextlib

with contextlib.suppress(FileNotFoundError):
    risky()
"""
    violations = error_mask_violations(source)
    assert not any(v["rule"] == "contextlib-suppress-broad" for v in violations)


def test_re_rasenot_a_mask():
    source = """
try:
    risky()
except Exception:
    logger.exception("failed")
    raise
"""
    violations = error_mask_violations(source)
    assert violations == []


def test_returns_sentinel_not_a_mask():
    source = """
try:
    risky()
except Exception:
    return Result.failure("could not compute")
"""
    violations = error_mask_violations(source)
    assert violations == []


def test_empty_except_body_is_mask():
    source = """
try:
    risky()
except Exception:
    pass
"""
    violations = error_mask_violations(source)
    assert len(violations) == 1
    assert violations[0]["line"] == 4


def test_malformed_source_returns_empty():
    violations = error_mask_violations("def broken(\n")
    assert violations == []


def test_detector_exposes_permitted_flag():
    source = """
try:
    risky()
except Exception:
    pass
"""
    matches = ErrorMaskDetector.check(source)
    assert len(matches) == 1
    assert not matches[0].permitted

    source_permitted = """
try:
    risky()
# error-mask-permitted: cause=expected recovery=continue
except Exception:
    pass
"""
    matches = ErrorMaskDetector.check(source_permitted)
    assert len(matches) == 1
    assert matches[0].permitted


# RACT 0.1.1 - Trust and Tooling
