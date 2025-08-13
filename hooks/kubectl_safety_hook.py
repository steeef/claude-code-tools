#!/usr/bin/env python3
"""
kubectl safety hook - allows read-only commands, prompts for destructive ones.
"""
import re
import shlex

# Read-only kubectl commands that are always safe
READ_ONLY_COMMANDS = {
    'get', 'describe', 'logs', 'top', 'version', 'cluster-info',
    'config', 'explain', 'api-resources', 'api-versions', 'diff'
}

# Destructive kubectl commands that require user approval
DESTRUCTIVE_COMMANDS = {
    'delete', 'apply', 'create', 'replace', 'patch', 'edit',
    'scale', 'rollout', 'annotate', 'label', 'expose', 'run',
    'exec', 'cp', 'port-forward', 'proxy'
}

def check_kubectl_command(command):
    """
    Check if kubectl command should be blocked for user approval.
    Returns (should_block, reason)
    """
    # Check if this is a kubectl command
    if not command.strip().startswith('kubectl'):
        return False, None

    try:
        # Parse the command to extract the kubectl subcommand
        parts = shlex.split(command)
        if len(parts) < 2:
            return False, None

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
            return False, None

        # Allow read-only commands
        if subcommand in READ_ONLY_COMMANDS:
            return False, None

        # Block destructive commands with user prompt
        if subcommand in DESTRUCTIVE_COMMANDS:
            # Check if this is a dry-run command (safe to allow)
            is_dry_run = any(
                part.startswith('--dry-run') for part in parts
            )

            if is_dry_run:
                # Allow dry-run commands without prompting
                return False, None

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
⚠️  Always verify the correct context and resources.

Type 'yes' to proceed or 'no' to cancel: """

            return True, reason

        # Block unknown kubectl commands as potentially dangerous
        return True, f"Unknown kubectl command '{subcommand}' blocked for safety. Known safe commands: {', '.join(sorted(READ_ONLY_COMMANDS))}"

    except Exception as e:
        # If we can't parse the command, be safe and allow it
        return False, None
