from ract.config import get_config


def test_config():
    config = get_config()
    assert config["title"] == "User-Configured Project Document"
    assert (
        config["description"]
        == "Each project has a configuration document (goals, constraints, style rules) that RACT reads and follows throughout the session."
    )
    assert config["tags"] == [
        "core",
        "configuration",
        "low-complexity",
        "high-priority",
    ]
