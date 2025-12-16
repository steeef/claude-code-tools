#!/usr/bin/env python3
"""
Worktree cleanup hook - auto-removes worktrees after PR merge.

Post-tool hook on Bash that detects merge completion and provides
cleanup instructions to Claude.
"""
import json
import os
import re
import shlex
import subprocess
import sys


def get_current_branch():
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def get_worktree_path():
    """Get the path of the current worktree if in one."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--git-dir'],
            capture_output=True,
            text=True,
            timeout=5
        )
        git_dir = result.stdout.strip() if result.returncode == 0 else None

        # If git-dir contains "worktrees", we're in a worktree
        if git_dir and 'worktrees' in git_dir:
            # Get the actual worktree directory
            result = subprocess.run(
                ['git', 'rev-parse', '--show-toplevel'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
    except Exception:
        pass
    return None


def get_main_repo_path():
    """Get the main repository path (not worktree)."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--git-common-dir'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            common_dir = result.stdout.strip()
            # The common dir is .git for main repo or points to main .git
            if common_dir.endswith('.git'):
                return os.path.dirname(common_dir)
            # Handle case where it's the .git directory itself
            if os.path.isdir(common_dir):
                parent = os.path.dirname(common_dir)
                if os.path.basename(common_dir) == '.git':
                    return parent
    except Exception:
        pass
    return None


def is_in_worktree():
    """Check if we're currently in a worktree."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--git-dir'],
            capture_output=True,
            text=True,
            timeout=5
        )
        git_dir = result.stdout.strip() if result.returncode == 0 else None
        return git_dir and 'worktrees' in git_dir
    except Exception:
        return False


def is_branch_merged_to_main(branch_name):
    """Check if a branch has been merged to main/master."""
    try:
        # Check if branch is merged into main
        for main_branch in ['main', 'master']:
            result = subprocess.run(
                ['git', 'branch', '--merged', main_branch],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                merged_branches = result.stdout.strip().split('\n')
                merged_branches = [b.strip().lstrip('* ') for b in merged_branches]
                if branch_name in merged_branches:
                    return True
    except Exception:
        pass
    return False


def detect_merge_command(command):
    """
    Detect if command indicates a merge completion.

    Detects:
    - gh pr merge
    - git pull (on main/master branch)
    - git merge (into main/master)
    """
    try:
        parts = shlex.split(command)
    except ValueError:
        return False, None

    # Detect gh pr merge
    if 'gh' in parts and 'pr' in parts and 'merge' in parts:
        return True, "gh_pr_merge"

    # Detect git pull on main branch
    if 'git' in parts and 'pull' in parts:
        current_branch = get_current_branch()
        if current_branch in ['main', 'master']:
            return True, "git_pull_main"

    return False, None


def check_cleanup_needed(command, tool_output):
    """
    Check if worktree cleanup should be triggered.

    Returns cleanup instructions if applicable.
    """
    is_merge, merge_type = detect_merge_command(command)

    if not is_merge:
        return None

    # Check if we're in a worktree
    if not is_in_worktree():
        return None

    worktree_path = get_worktree_path()
    current_branch = get_current_branch()
    main_repo = get_main_repo_path()

    if not worktree_path or not current_branch:
        return None

    # For gh pr merge, check if the PR was for our current branch
    if merge_type == "gh_pr_merge":
        # The branch is being merged - cleanup needed
        cleanup_msg = f"""WORKTREE CLEANUP TRIGGERED

PR merged for branch: {current_branch}
Worktree location: {worktree_path}

To clean up:
1. cd {main_repo}
2. git worktree remove "{worktree_path}"
3. git branch -d {current_branch}

Announce to user:
  "PR merged. Cleaning up worktree at {worktree_path}"
"""
        return cleanup_msg

    # For git pull on main, check if any worktree branches are now merged
    if merge_type == "git_pull_main":
        if is_branch_merged_to_main(current_branch):
            cleanup_msg = f"""WORKTREE CLEANUP - BRANCH MERGED

Branch {current_branch} is now merged to main.
Worktree location: {worktree_path}

To clean up:
1. cd {main_repo}
2. git worktree remove "{worktree_path}"
3. git branch -d {current_branch}

Announce to user:
  "Branch merged. Cleaning up worktree at {worktree_path}"
"""
            return cleanup_msg

    return None


def main():
    data = json.load(sys.stdin)

    # Check if this is a Bash tool call
    tool_name = data.get("tool_name")
    if tool_name != "Bash":
        print(json.dumps({"decision": "approve"}))
        sys.exit(0)

    # Get the command and output
    command = data.get("tool_input", {}).get("command", "")
    tool_output = data.get("tool_output", {}).get("stdout", "")

    cleanup_instructions = check_cleanup_needed(command, tool_output)

    if cleanup_instructions:
        print(json.dumps({
            "additionalContext": cleanup_instructions
        }))
    else:
        print(json.dumps({"decision": "approve"}))

    sys.exit(0)


if __name__ == "__main__":
    main()
