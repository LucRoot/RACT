__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
from rootact.experimental.skills import register_skill

def test_register_skill():
    """Test the register_skill function."""
    result = register_skill("test_skill", {"x": 1})
    assert result == {"test_skill": {"x": 1}}
