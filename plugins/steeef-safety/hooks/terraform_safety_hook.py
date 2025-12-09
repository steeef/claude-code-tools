#!/usr/bin/env python3
"""
Terraform safety hook - allows read-only commands, blocks apply operations.
Supports three decision types: allow, ask (user prompt), block (deny).
"""
import json
import sys
import shlex

# Read-only terraform commands that are always safe
READ_ONLY_COMMANDS = {
    'plan', 'show', 'validate', 'version', 'providers', 'output',
    'state', 'graph', 'console', 'fmt', 'get', 'init', 'workspace'
}

# Destructive terraform commands that require user approval
DESTRUCTIVE_COMMANDS = {
    'apply', 'destroy', 'import', 'taint', 'untaint', 'refresh'
}


def check_terraform_command(command):
    """
    Check if terraform command should be blocked for user approval.
    Returns (decision, reason) where decision is "allow", "ask", or "block".
    """
    # Check if this is a terraform or tf command
    if not (command.strip().startswith('terraform') or command.strip().startswith('tf ')):
        return ("allow", None)

    try:
        # Parse the command to extract the terraform subcommand
        parts = shlex.split(command)
        if len(parts) < 2:
            return ("allow", None)

        # Skip 'terraform'/'tf' and any global flags to find the subcommand
        subcommand = None
        skip_next = False
        for part in parts[1:]:
            if skip_next:
                skip_next = False
                continue
            if part.startswith('-'):
                # Handle flags with values like -chdir=/path
                if '=' not in part and part in ['-chdir', '-var', '-var-file']:
                    skip_next = True
                continue
            else:
                subcommand = part
                break

        if not subcommand:
            return ("allow", None)

        # Allow read-only commands
        if subcommand in READ_ONLY_COMMANDS:
            return ("allow", None)

        # Block destructive commands
        if subcommand in DESTRUCTIVE_COMMANDS:
            # Extract workspace if we can determine it
            workspace = "default"

            reason = f"""🚨 DESTRUCTIVE terraform COMMAND DETECTED

Command: {command}
Workspace: {workspace}
Action: {subcommand.upper()}

This command can modify or destroy infrastructure resources.

⚠️  This could impact running services and infrastructure.
⚠️  Always verify the correct workspace and resources with 'terraform plan' first."""

            return ("block", reason)

        # Block unknown terraform commands as potentially dangerous
        return ("block", f"Unknown terraform command '{subcommand}' blocked for safety. Known safe commands: {', '.join(sorted(READ_ONLY_COMMANDS))}")

    except Exception:
        # If we can't parse the command, be safe and allow it
        return ("allow", None)


def main():
    data = json.load(sys.stdin)

    # Check if this is a Bash tool call
    tool_name = data.get("tool_name")
    if tool_name != "Bash":
        print(json.dumps({"decision": "approve"}))
        sys.exit(0)

    # Get the command being executed
    command = data.get("tool_input", {}).get("command", "")

    decision, reason = check_terraform_command(command)

    if decision == "block":
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason
            }
        }, ensure_ascii=False))
    elif decision == "ask":
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": reason
            }
        }))
    else:
        print(json.dumps({"decision": "approve"}))

    sys.exit(0)


if __name__ == "__main__":
    main()
