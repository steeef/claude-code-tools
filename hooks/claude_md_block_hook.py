#!/usr/bin/env python3
"""
Hook to prevent writing to CLAUDE.md files and suggest writing to AGENTS.md instead.
This ensures proper version control and management of project-specific instructions.
"""
import json
import sys
import os


def check_claude_md_write(tool_name, tool_input):
    """
    Check if a tool call attempts to write to CLAUDE.md files.
    Returns tuple: (should_block: bool, reason: str or None)
    """
    # Only check file writing tools
    if tool_name not in ["Write", "Edit", "MultiEdit"]:
        return False, None

    # Get the file path from tool input
    file_path = None
    if tool_name == "Write":
        file_path = tool_input.get("file_path")
    elif tool_name == "Edit":
        file_path = tool_input.get("file_path")
    elif tool_name == "MultiEdit":
        file_path = tool_input.get("file_path")

    if not file_path:
        return False, None

    # Normalize the file path to check if it's a CLAUDE.md file
    normalized_path = os.path.normpath(file_path).lower()

    # Check if the file is named CLAUDE.md (case insensitive)
    if normalized_path.endswith("/claude.md") or normalized_path == "claude.md":
        reason_text = (
            "Blocked: Direct writing to CLAUDE.md files is not allowed.\n\n"
            "Instead of creating/editing CLAUDE.md, please:\n\n"
            "1. Write your content to AGENTS.md\n"
            "2. Then create a symlink: ln -s AGENTS.md CLAUDE.md\n\n"
            "This approach ensures proper version control and management of "
            "project-specific instructions for AI coding agents.\n\n"
            "AGENTS.md should contain general instructions for AI coding agents, "
            "not Claude Code-specific references."
        )
        return True, reason_text

    return False, None


def main():
    data = json.load(sys.stdin)

    # Get tool information
    tool_name = data.get("tool_name")
    tool_input = data.get("tool_input", {})

    # Check if this tool call should be blocked
    should_block, reason = check_claude_md_write(tool_name, tool_input)

    if should_block:
        print(json.dumps({
            "decision": "block",
            "reason": reason
        }, ensure_ascii=False))
    else:
        print(json.dumps({"decision": "approve"}))

    sys.exit(0)


if __name__ == "__main__":
    main()
