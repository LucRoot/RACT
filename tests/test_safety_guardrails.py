from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

import pytest

from rootact.safety_guardrails import SafetyGuardrail

_ROOT_KNOT = object()


def test_no_violations_for_safe_content() -> None:
    guard = SafetyGuardrail([{"pattern": r"eval\(", "name": "no-eval"}])
    assert guard.check("safe.py", "print('hello')") == []


def test_detects_forbidden_pattern() -> None:
    guard = SafetyGuardrail(
        [{"pattern": r"eval\(", "name": "no-eval", "message": "eval is unsafe"}]
    )
    violations = guard.check("bad.py", "result = eval(user_input)")
    assert len(violations) == 1
    assert violations[0]["rule"] == "no-eval"
    assert violations[0]["message"] == "eval is unsafe"
    assert violations[0]["path"] == "bad.py"
    assert violations[0]["line"] == 1


def test_missing_pattern_raises() -> None:
    with pytest.raises(ValueError, match="pattern"):
        SafetyGuardrail([{"name": "no-eval"}])  # type: ignore[arg-type]


def test_check_files_aggregates() -> None:
    guard = SafetyGuardrail([{"pattern": r"exec\(", "name": "no-exec"}])
    files = {"a.py": "exec('x')", "b.py": "print('ok')", "c.py": "exec('y')"}
    violations = guard.check_files(files)
    assert len(violations) == 2
    assert {v["path"] for v in violations} == {"a.py", "c.py"}


def test_default_rule_name_uses_pattern() -> None:
    guard = SafetyGuardrail([{"pattern": r"os\.system"}])
    violations = guard.check("x.py", "os.system('rm -rf /')")
    assert violations[0]["rule"] == r"os\.system"


def test_line_number_reported() -> None:
    guard = SafetyGuardrail([{"pattern": r"eval\(", "name": "no-eval"}])
    content = "print(1)\nprint(2)\nresult = eval(user_input)\n"
    violations = guard.check("bad.py", content)
    assert violations[0]["line"] == 3


def test_detects_error_mask_in_python_source() -> None:
    guard = SafetyGuardrail([])
    content = """
try:
    risky()
except Exception:
    pass
"""
    violations = guard.check("bad.py", content)
    assert any(v["rule"] == "except-pass" for v in violations)


def test_error_mask_can_be_disabled() -> None:
    guard = SafetyGuardrail([], check_error_masks=False)
    content = """
try:
    risky()
except Exception:
    pass
"""
    violations = guard.check("bad.py", content)
    assert violations == []


def test_error_mask_permitted_by_comment() -> None:
    guard = SafetyGuardrail([])
    content = """
try:
    risky()
# error-mask-permitted: cause=expected recovery=continue
except Exception:
    pass
"""
    violations = guard.check("bad.py", content)
    assert not any(v["rule"] == "except-pass" for v in violations)


# RACT 0.1.0 - Initial Public Release
