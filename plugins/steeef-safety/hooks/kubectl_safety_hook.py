#!/usr/bin/env python3
"""
kubectl safety hook - allows read-only commands, prompts for destructive ones.
Supports three decision types: allow, ask (user prompt), block (deny).
"""
import json
import sys
import shlex

# Read-only kubectl commands that are always safe
READ_ONLY_COMMANDS = {
    'get', 'describe', 'logs', 'top', 'version', 'cluster-info',
    'config', 'explain', 'api-resources', 'api-versions', 'diff'
}

# Destructive kubectl commands that require user approval (blocks)
DESTRUCTIVE_COMMANDS = {
    'delete', 'apply', 'create', 'replace', 'patch', 'edit',
    'scale', 'rollout', 'annotate', 'label', 'expose', 'run',
    'exec', 'cp'
}

# Commands that ask for permission instead of blocking
ASK_PERMISSION_COMMANDS = {'port-forward', 'proxy'}


def check_kubectl_command(command):
    """
    Check if kubectl command should be blocked or ask for user approval.
    Returns (decision, reason) where decision is "allow", "ask", or "block".
    """
    # Check if this is a kubectl command
    if not command.strip().startswith('kubectl'):
        return ("allow", None)

    try:
        # Parse the command to extract the kubectl subcommand
        parts = shlex.split(command)
        if len(parts) < 2:
            return ("allow", None)

        # Skip 'kubectl' and any global flags to find the subcommand
        subcommand = None
        skip_next = False
        for part in parts[1:]:
            if skip_next:
                skip_next = False
                continue
            if part.startswith('-'):
                # Handle flags with values like --context ops
                if '=' not in part and part in ['--context', '--namespace', '-n', '--kubeconfig']:
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

        # Block destructive commands with user prompt
        if subcommand in DESTRUCTIVE_COMMANDS:
            # Check if this is a dry-run command (safe to allow)
            is_dry_run = any(
                part.startswith('--dry-run') for part in parts
            )

            if is_dry_run:
                # Allow dry-run commands without prompting
                return ("allow", None)

            # Extract context if present
            context = "default"
            for i, part in enumerate(parts):
                if part == '--context' and i + 1 < len(parts):
                    context = parts[i + 1]
                    break

            reason = f"""🚨 DESTRUCTIVE kubectl COMMAND DETECTED

Command: {command}
Context: {context}
Action: {subcommand.upper()}

This command can modify or delete Kubernetes resources.

⚠️  This could impact running applications and services.
⚠️  Always verify the correct context and resources."""

            return ("block", reason)

        # Ask permission for port-forward and similar commands
        if subcommand in ASK_PERMISSION_COMMANDS:
            # Extract context if present
            context = "default"
            for i, part in enumerate(parts):
                if part == '--context' and i + 1 < len(parts):
                    context = parts[i + 1]
                    break

            reason = f"""kubectl {subcommand.upper()} requested

Command: {command}
Context: {context}

This will establish a connection to the cluster."""

            return ("ask", reason)

        # Block unknown kubectl commands as potentially dangerous
        return ("block", f"Unknown kubectl command '{subcommand}' blocked for safety. Known safe commands: {', '.join(sorted(READ_ONLY_COMMANDS))}")

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

    decision, reason = check_kubectl_command(command)

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
