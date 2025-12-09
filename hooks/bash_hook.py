#!/usr/bin/env python3
"""
Unified Bash hook that combines all bash command safety checks.
This ensures that if ANY check wants to block, the command is blocked.
"""
import json
import sys
import os

# Add hooks directory to Python path so we can import the other modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import check functions from other hooks
from git_add_block_hook import check_git_add_command
from git_checkout_safety_hook import check_git_checkout_command
from git_commit_block_hook import check_git_commit_command
from rm_block_hook import check_rm_command
from env_file_protection_hook import check_env_file_access
from kubectl_safety_hook import check_kubectl_command
from terraform_safety_hook import check_terraform_command


def main():
    data = json.load(sys.stdin)

    # Check if this is a Bash tool call
    tool_name = data.get("tool_name")
    if tool_name != "Bash":
        # Empty output = no opinion, let Claude Code handle normally
        print(json.dumps({}))
        sys.exit(0)

    # Get the command being executed
    command = data.get("tool_input", {}).get("command", "")

    # Run all checks - collect blocking and ask reasons separately
    # Checks that return 2 values: (should_block, reason)
    two_value_checks = [
        check_rm_command,
        check_git_add_command,
        check_git_checkout_command,
        check_git_commit_command,
        check_env_file_access,
        check_terraform_command,
    ]

    blocking_reasons = []
    ask_reasons = []

    for check_func in two_value_checks:
        should_block, reason = check_func(command)
        if should_block:
            blocking_reasons.append(reason)

    # kubectl check returns 3 values: (should_prompt, reason, decision_type)
    should_prompt, reason, decision_type = check_kubectl_command(command)
    if should_prompt:
        if decision_type == "ask":
            ask_reasons.append(reason)
        else:
            blocking_reasons.append(reason)

    # If any check wants to block, block takes precedence
    if blocking_reasons:
        # If multiple checks want to block, combine the reasons
        if len(blocking_reasons) == 1:
            combined_reason = blocking_reasons[0]
        else:
            combined_reason = "Multiple safety checks failed:\n\n"
            for i, reason in enumerate(blocking_reasons, 1):
                combined_reason += f"{i}. {reason}\n\n"

        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": combined_reason,
                    }
                },
                ensure_ascii=False,
            )
        )
    elif ask_reasons:
        # Ask for permission (doesn't block, but requires user approval)
        combined_reason = ask_reasons[0] if len(ask_reasons) == 1 else "\n\n".join(ask_reasons)
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "ask",
                        "permissionDecisionReason": combined_reason,
                    }
                },
                ensure_ascii=False,
            )
        )
    else:
        print(json.dumps({}))

    sys.exit(0)


if __name__ == "__main__":
    main()
