__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

def validate_config(config):
    required_keys = {"title", "description", "tags"}
    if not required_keys.issubset(config.keys()):
        return False
    if not isinstance(config["title"], str):
        return False
    if not isinstance(config["description"], str):
        return False
    if not isinstance(config["tags"], list):
        return False
    return True
