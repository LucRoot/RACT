def create_cli_tool(tool_description):
    title = tool_description.get("title", "")
    description = tool_description.get("description", "")
    tags = tool_description.get("tags", [])

    tool = {"title": title, "description": description, "tags": tags}

    return tool
