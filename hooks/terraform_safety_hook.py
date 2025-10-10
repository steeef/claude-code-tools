#!/usr/bin/env python3
"""
Terraform safety hook - allows read-only commands, blocks apply operations.
"""
import re
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
    Returns (should_block, reason)
    """
    # Check if this is a terraform or tf command
    if not (command.strip().startswith('terraform') or command.strip().startswith('tf ')):
        return False, None

    try:
        # Parse the command to extract the terraform subcommand
        parts = shlex.split(command)
        if len(parts) < 2:
            return False, None

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
            return False, None

        # Allow read-only commands
        if subcommand in READ_ONLY_COMMANDS:
            return False, None

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
⚠️  Always verify the correct workspace and resources with 'terraform plan' first.

Type 'yes' to proceed or 'no' to cancel: """

            return True, reason

        # Block unknown terraform commands as potentially dangerous
        return True, f"Unknown terraform command '{subcommand}' blocked for safety. Known safe commands: {', '.join(sorted(READ_ONLY_COMMANDS))}"

    except Exception as e:
        # If we can't parse the command, be safe and allow it
        return False, None


# If run as a standalone script
if __name__ == "__main__":
    import json
    import sys

    data = json.load(sys.stdin)

    # Check if this is a Bash tool call
    tool_name = data.get("tool_name")
    if tool_name != "Bash":
        print(json.dumps({"decision": "approve"}))
        sys.exit(0)

    # Get the command being executed
    command = data.get("tool_input", {}).get("command", "")

    should_block, reason = check_terraform_command(command)

    if should_block:
        print(json.dumps({
            "decision": "block",
            "reason": reason
        }, ensure_ascii=False))
    else:
        print(json.dumps({"decision": "approve"}))

    sys.exit(0)
