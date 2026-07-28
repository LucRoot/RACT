from ract.config_validation import validate_config


def get_config():
    config = {
        "title": "User-Configured Project Document",
        "description": "Each project has a configuration document (goals, constraints, style rules) that RACT reads and follows throughout the session.",
        "tags": ["core", "configuration", "low-complexity", "high-priority"],
    }
    if not validate_config(config):
        raise ValueError("invalid configuration document")
    return config
