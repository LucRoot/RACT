__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
from ract.experimental.skills import register_skill


def test_register_skill_config():
    """Test the register_skill function with a config."""
    result = register_skill("test_skill", {"x": 2, "y": 3})
    assert result == {"test_skill": {"x": 2, "y": 3}}
