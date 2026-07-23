__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

def register_skill(skill_name, skill_config):
    """Register a custom skill with a name and configuration."""
    skills = {}
    skills.setdefault(skill_name, {}).update(skill_config)
    return skills
