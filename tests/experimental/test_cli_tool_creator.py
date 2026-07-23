__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
from ract.experimental.cli_tool_creator import create_cli_tool


def test_create_cli_tool():
    tool_description = {
        "title": "Custom CLI Tool Creation from Natural Language",
        "description": "A data analyst describes a small CLI they need; RACT generates a Python script, argparse wiring, and a minimal test harness.",
        "tags": ["core", "cli", "medium-complexity", "high-priority"],
    }

    tool = create_cli_tool(tool_description)

    assert tool["title"] == "Custom CLI Tool Creation from Natural Language"
    assert (
        tool["description"]
        == "A data analyst describes a small CLI they need; RACT generates a Python script, argparse wiring, and a minimal test harness."
    )
    assert tool["tags"] == ["core", "cli", "medium-complexity", "high-priority"]
