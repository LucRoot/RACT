__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

from rootact.config_validation import validate_config

def get_config():
    config = {
        "title": "User-Configured Project Document",
        "description": "Each project has a configuration document (goals, constraints, style rules) that RootAct reads and follows throughout the session.",
        "tags": ["core", "configuration", "low-complexity", "high-priority"]
    }
    if not validate_config(config):
        raise ValueError("invalid configuration document")
    return config
