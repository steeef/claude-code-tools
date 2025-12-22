#!/usr/bin/env python3
"""
Git branch workflow enforcement hook.

Enforces branch-based development workflow:
- Block commits on main/master (must create Jira-prefixed branch)
- Block git stash store operations (can bypass workflow)
- Ask for Jira issue when creating branch without prefix
- Validate branch names have Jira prefix (PROJ-123 pattern)
"""
import json
import re
import shlex
import subprocess
import sys
from typing import Optional, Tuple


# Jira issue pattern: uppercase letters followed by dash and numbers
JIRA_PATTERN = re.compile(r'^[A-Z]+-\d+')

# Protected branches that should not have direct commits
PROTECTED_BRANCHES = {'main', 'master'}

# Stash subcommands that store changes (warn about these)
STASH_STORE_SUBCOMMANDS = {'push', 'save', ''}  # empty string = bare 'git stash'

# Stash subcommands that retrieve/manage (allow these)
STASH_RETRIEVE_SUBCOMMANDS = {'pop', 'apply', 'list', 'drop', 'clear', 'show', 'branch'}


def get_current_branch(cwd: Optional[str] = None) -> Optional[str]:
    """Get current git branch name, optionally in a specific directory."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def extract_cd_target(command: str) -> Optional[str]:
    """
    Extract the target directory from a cd command.
    Returns expanded path or None if not a cd command.
    """
    import os
    try:
        parts = shlex.split(command)
        if parts and parts[0] == 'cd' and len(parts) >= 2:
            target = parts[1]
            # Expand ~ to home directory
            return os.path.expanduser(target)
    except Exception:
        pass
    return None


def extract_subcommands(command: str) -> list[str]:
    """Split compound commands on &&, ||, and ;"""
    subcommands = re.split(r'\s*(?:&&|\|\||;)\s*', command)
    return [cmd.strip() for cmd in subcommands if cmd.strip()]


def extract_new_branch_name(command: str) -> Optional[str]:
    """
    Extract branch name from branch creation commands.
    Supports: git checkout -b <branch>, git switch -c <branch>
    Returns None if not a branch creation command.
    """
    try:
        parts = shlex.split(command)
        if len(parts) < 4:
            return None

        # git checkout -b <branch> [start-point]
        if parts[0] == 'git' and parts[1] == 'checkout' and '-b' in parts:
            idx = parts.index('-b')
            if idx + 1 < len(parts):
                return parts[idx + 1]

        # git switch -c <branch> [start-point] or git switch --create <branch>
        if parts[0] == 'git' and parts[1] == 'switch':
            if '-c' in parts:
                idx = parts.index('-c')
                if idx + 1 < len(parts):
                    return parts[idx + 1]
            if '--create' in parts:
                idx = parts.index('--create')
                if idx + 1 < len(parts):
                    return parts[idx + 1]

    except Exception:
        pass
    return None


def _check_single_subcommand(subcmd: str, cwd: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """
    Check a single subcommand for git workflow rules.
    Returns (decision, reason) where decision is "allow", "ask", or "block".
    """
    normalized = subcmd.strip().lower()

    # Check for git commit
    if normalized.startswith('git commit'):
        branch = get_current_branch(cwd=cwd)
        if branch is None:
            # Can't determine branch, allow and let git handle it
            return ("allow", None)

        if branch in PROTECTED_BRANCHES:
            reason = f"""🚫 COMMIT ON PROTECTED BRANCH BLOCKED

Cannot commit directly to '{branch}'.

Required workflow:
1. Create a feature branch with Jira prefix: git checkout -b PROJ-123-description
2. Make your changes and commit there
3. Create a PR to merge back"""
            return ("block", reason)

        # Check if branch has Jira prefix
        if not JIRA_PATTERN.match(branch):
            reason = f"""⚠️  BRANCH MISSING JIRA PREFIX

Current branch: {branch}

Branch names should start with a Jira issue (e.g., ORG-123-feature-description).

This helps track work back to tickets. Continue with this branch name?"""
            return ("ask", reason)

        # Branch is properly named, still ask for commit approval
        return ("ask", "Git commit requires your approval.")

    # Check for git stash
    if normalized.startswith('git stash'):
        try:
            parts = shlex.split(subcmd)
            # Get stash subcommand (or empty string for bare 'git stash')
            stash_subcmd = parts[2] if len(parts) > 2 else ''

            if stash_subcmd in STASH_RETRIEVE_SUBCOMMANDS:
                # Allow retrieval operations
                return ("allow", None)

            if stash_subcmd in STASH_STORE_SUBCOMMANDS or stash_subcmd.startswith('-'):
                reason = """🚫 GIT STASH BLOCKED

git stash bypasses the branch workflow by hiding uncommitted changes.

Required workflow:
1. Create a feature branch: git checkout -b PROJ-123-wip
2. Commit your work-in-progress there"""
                return ("block", reason)

        except Exception:
            pass

    # Check for branch creation without Jira prefix
    new_branch = extract_new_branch_name(subcmd)
    if new_branch and not JIRA_PATTERN.match(new_branch):
        reason = f"""⚠️  BRANCH MISSING JIRA PREFIX

Proposed branch: {new_branch}

Branch names should start with a Jira issue (e.g., ORG-123-{new_branch}).

What's the Jira issue for this work? Or continue with this name?"""
        return ("ask", reason)

    return ("allow", None)


def check_git_branch_workflow(command: str) -> Tuple[str, Optional[str]]:
    """
    Check if git command should prompt for branch workflow.
    Returns (decision, reason) where decision is "allow", "ask", or "block".

    Checks ALL subcommands in compound commands and applies priority:
    block > ask > allow

    Tracks working directory context from cd commands to correctly
    determine branch in worktrees.
    """
    block_reasons = []
    ask_reasons = []
    current_cwd = None  # Track working directory from cd commands

    for subcmd in extract_subcommands(command):
        # Check if this is a cd command and update context
        cd_target = extract_cd_target(subcmd)
        if cd_target:
            current_cwd = cd_target
            continue  # cd itself doesn't need workflow checks

        decision, reason = _check_single_subcommand(subcmd, cwd=current_cwd)
        if decision == "block":
            block_reasons.append(reason)
        elif decision == "ask":
            ask_reasons.append(reason)

    # Priority: block > ask > allow
    if block_reasons:
        # Return first block reason (could combine if multiple)
        return ("block", block_reasons[0])
    elif ask_reasons:
        # Return first ask reason
        return ("ask", ask_reasons[0])

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

    decision, reason = check_git_branch_workflow(command)

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
        }, ensure_ascii=False))
    else:
        print(json.dumps({"decision": "approve"}))

    sys.exit(0)


if __name__ == "__main__":
    main()
