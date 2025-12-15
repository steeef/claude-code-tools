#!/usr/bin/env python3
"""
Git commit hook that asks for user permission before allowing commits.
Uses the "ask" decision type to prompt user in the UI.
"""
import json
import sys

from command_utils import extract_subcommands


def check_git_commit_command(command):
    """
    Check if a command contains a git commit and request user permission.
    Handles compound commands (e.g., "cd /path && git commit -m 'msg'").

    Returns tuple: (decision: str, reason: str or None)

    decision is one of: "allow", "ask", "block"
    """
    # Check each subcommand in compound commands
    for subcmd in extract_subcommands(command):
        normalized = ' '.join(subcmd.strip().split())
        if normalized.startswith('git commit'):
            reason = "Git commit requires your approval."
            return "ask", reason

    return "allow", None


# If run as a standalone script
if __name__ == "__main__":
    data = json.load(sys.stdin)

    # Check if this is a Bash tool call
    tool_name = data.get("tool_name")
    if tool_name != "Bash":
        print(json.dumps({"decision": "approve"}))
        sys.exit(0)

    # Get the command being executed
    command = data.get("tool_input", {}).get("command", "")

    decision, reason = check_git_commit_command(command)

    if decision == "ask":
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": reason
            }
        }))
    elif decision == "block":
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason
            }
        }))
    else:
        print(json.dumps({"decision": "approve"}))

    sys.exit(0)
