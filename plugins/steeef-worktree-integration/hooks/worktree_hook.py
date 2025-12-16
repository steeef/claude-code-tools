#!/usr/bin/env python3
"""
Worktree hook - suggests worktree usage when creating feature branches.

Pre-tool hook on Bash that detects branch creation commands and provides
guidance to Claude about using git worktrees for feature work.
"""
import json
import os
import re
import shlex
import subprocess
import sys


# Patterns that indicate feature branch creation (not hotfixes)
FEATURE_BRANCH_PATTERNS = [
    r'^(feature|feat)/',
    r'^add-',
    r'^implement-',
    r'^create-',
    r'^build-',
    r'^refactor/',
]

# Patterns for branches that should NOT trigger worktree suggestion
SKIP_PATTERNS = [
    r'^(hotfix|fix)/',
    r'^(docs|doc)/',
    r'^(chore)/',
    r'^(bump|release|version)',
]


def get_repo_root():
    """Get the git repository root directory."""
    try:
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


def get_repo_name(repo_root):
    """Extract repository name from path."""
    if repo_root:
        return os.path.basename(repo_root)
    return None


def determine_worktree_location(repo_root):
    """
    Determine worktree location based on repo path.

    - Work repos (under ~/code/work/) -> ~/code/work/.worktrees/<repo>/
    - Other repos -> ~/code/.worktrees/<repo>/
    """
    if not repo_root:
        return None

    work_prefix = os.path.expanduser("~/code/work")
    repo_name = get_repo_name(repo_root)

    if repo_root.startswith(work_prefix):
        return os.path.join(work_prefix, ".worktrees", repo_name)
    else:
        return os.path.join(os.path.expanduser("~/code"), ".worktrees", repo_name)


def is_feature_branch(branch_name):
    """Check if branch name suggests feature work."""
    for pattern in SKIP_PATTERNS:
        if re.match(pattern, branch_name, re.IGNORECASE):
            return False

    # Check for explicit feature patterns
    for pattern in FEATURE_BRANCH_PATTERNS:
        if re.match(pattern, branch_name, re.IGNORECASE):
            return True

    # Assume most non-skip branches are features
    # (user can ignore suggestion if not applicable)
    return True


def extract_branch_from_command(command):
    """
    Extract branch name from git branch creation commands.

    Handles:
    - git checkout -b <branch>
    - git switch -c <branch>
    - git branch <branch> && git checkout <branch>
    """
    try:
        parts = shlex.split(command)
    except ValueError:
        return None

    # Look for checkout -b pattern
    if 'checkout' in parts and '-b' in parts:
        try:
            idx = parts.index('-b')
            if idx + 1 < len(parts):
                return parts[idx + 1]
        except (ValueError, IndexError):
            pass

    # Look for switch -c pattern
    if 'switch' in parts and '-c' in parts:
        try:
            idx = parts.index('-c')
            if idx + 1 < len(parts):
                return parts[idx + 1]
        except (ValueError, IndexError):
            pass

    # Look for switch --create pattern
    if 'switch' in parts and '--create' in parts:
        try:
            idx = parts.index('--create')
            if idx + 1 < len(parts):
                return parts[idx + 1]
        except (ValueError, IndexError):
            pass

    return None


def is_already_in_worktree():
    """Check if we're currently in a worktree (not the main repo)."""
    try:
        # git worktree list --porcelain shows all worktrees
        # The first entry is the main working tree
        result = subprocess.run(
            ['git', 'rev-parse', '--git-common-dir'],
            capture_output=True,
            text=True,
            timeout=5
        )
        git_common = result.stdout.strip() if result.returncode == 0 else None

        result = subprocess.run(
            ['git', 'rev-parse', '--git-dir'],
            capture_output=True,
            text=True,
            timeout=5
        )
        git_dir = result.stdout.strip() if result.returncode == 0 else None

        # If git-dir contains "worktrees", we're in a worktree
        if git_dir and 'worktrees' in git_dir:
            return True

        # Alternative check: if common-dir != git-dir, we're in a worktree
        if git_common and git_dir and git_common != git_dir:
            return True

    except Exception:
        pass

    return False


def check_worktree_suggestion(command):
    """
    Check if we should suggest worktree usage for this command.

    Returns (decision, reason) where decision is "allow" (with optional suggestion)
    """
    # Only check git commands
    if not command.strip().startswith('git '):
        return ("allow", None)

    # Extract branch name from command
    branch_name = extract_branch_from_command(command)
    if not branch_name:
        return ("allow", None)

    # Skip if already in a worktree
    if is_already_in_worktree():
        return ("allow", None)

    # Skip non-feature branches
    if not is_feature_branch(branch_name):
        return ("allow", None)

    # Get repo info
    repo_root = get_repo_root()
    worktree_location = determine_worktree_location(repo_root)

    if not worktree_location:
        return ("allow", None)

    full_worktree_path = os.path.join(worktree_location, branch_name)

    suggestion = f"""WORKTREE SUGGESTION

You're creating a feature branch: {branch_name}

Consider using a git worktree for this feature work:
  Location: {full_worktree_path}

To create the worktree instead:
  git worktree add "{full_worktree_path}" -b {branch_name}

Then announce to user:
  "Creating worktree for feature work. Working in: {full_worktree_path}"

Proceeding with regular branch creation is also fine for smaller changes."""

    # We return allow but include the suggestion as additional context
    # The hook doesn't block, just provides guidance
    return ("allow", suggestion)


def main():
    data = json.load(sys.stdin)

    # Check if this is a Bash tool call
    tool_name = data.get("tool_name")
    if tool_name != "Bash":
        print(json.dumps({"decision": "approve"}))
        sys.exit(0)

    # Get the command being executed
    command = data.get("tool_input", {}).get("command", "")

    decision, suggestion = check_worktree_suggestion(command)

    if suggestion:
        # Provide suggestion as additional context but allow the command
        print(json.dumps({
            "decision": "approve",
            "additionalContext": suggestion
        }))
    else:
        print(json.dumps({"decision": "approve"}))

    sys.exit(0)


if __name__ == "__main__":
    main()
