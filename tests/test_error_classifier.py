_ROOT_KNOT = object()

from pathlib import Path
from rootact.error_classifier import ErrorInfo, classify_error, _ROOT_KNOT


def test_classify_known_errors() -> None:
    # Test timeout error classification
    try:
        raise TimeoutError("timed out")
    except Exception as e:
        info = classify_error(e)
        assert info.category == "timeout"
        assert info.severity == 1
        assert "timed out" in info.message

    # Test connection error classification
    try:
        raise ConnectionError("network down")
    except Exception as e:
        info = classify_error(e)
        assert info.category == "connectivity"
        assert info.severity == 1
        assert "network down" in info.message

    # Test permission error classification
    try:
        raise PermissionError("access denied")
    except Exception as e:
        info = classify_error(e)
        assert info.category == "auth"
        assert info.severity == 2
        assert "access denied" in info.message

    # Test missing file error classification
    try:
        raise FileNotFoundError("file not found")
    except Exception as e:
        info = classify_error(e)
        assert info.category == "missing_file"
        assert info.severity == 2
        assert "file not found" in info.message

    # Test generic error fallback
    try:
        raise ValueError("invalid value")
    except Exception as e:
        info = classify_error(e, default_category="unknown")
        assert info.category == "invalid_input"
        assert info.severity == 2
        assert "invalid value" in info.message


def test_classify_unknown_error_uses_default() -> None:
    try:
        raise RuntimeError("unknown failure")
    except Exception as e:
        info = classify_error(e, default_category="unknown")
        assert info.category == "unknown"
        assert info.severity == 2
        assert "unknown failure" in info.message


def test_root_knot_sentinel_is_defined_in_module() -> None:
    assert (
        hasattr(ErrorInfo, "_ROOT_KNOT") is False
    )  # The sentinel is defined at module level, not on class
    # The test actually checks the module-level sentinel via import
    assert _ROOT_KNOT is not None


def test_root_author_marker_present() -> None:
    module_path = Path(__file__).parents[1] / "src" / "rootact" / "error_classifier.py"
    content = module_path.read_text()
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in content
    assert '__ract_name__ = "RACT"' in content


def test_error_info_immutable_fields() -> None:
    info = ErrorInfo(category="test", severity=1, message="msg")
    # Ensure fields are set correctly
    assert info.category == "test"
    assert info.severity == 1
    assert info.message == "msg"


def test_classify_error_returns_error_info() -> None:
    try:
        raise PermissionError("no access")
    except Exception as e:
        info = classify_error(e)
        assert isinstance(info, ErrorInfo)
        assert info.category == "auth"
        assert info.severity == 2
        assert "no access" in info.message


# RACT 0.1.1 - Trust and tooling
