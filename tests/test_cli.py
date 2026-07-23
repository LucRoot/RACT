__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
import pytest
from rootact.cli import toggle_mode

def test_toggle_mode():
    """Test toggle_mode function."""
    assert toggle_mode("yolo") == "yolo"
    assert toggle_mode("auto") == "auto"
    assert toggle_mode("dry-run") == "dry-run"
    assert toggle_mode("reload") == "reload"
    assert toggle_mode("resume") == "resume"
    with pytest.raises(ValueError):
        toggle_mode("invalid")
