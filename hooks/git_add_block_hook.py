#!/usr/bin/env python3
import re

def check_git_add_command(command):
    """
    Check if a git add command contains dangerous patterns.
    Returns tuple: (should_block: bool, reason: str or None)
    """
    # Normalize the command - handle multiple spaces, tabs, etc.
    normalized_cmd = ' '.join(command.strip().split())
    
    # Pattern to match git add with problematic flags
    # This catches: git add -A, git add --all, git add -a, git add ., and combined flags
    # We need to match these as standalone arguments, not as part of filenames
    git_add_pattern = re.compile(
        r'^git\s+add\s+('
        r'-[a-zA-Z]*[Aa][a-zA-Z]*(\s|$)|'  # Flags containing 'A' or 'a' (e.g., -A, -a, -fA, -Af)
        r'--all(\s|$)|'                     # Long form --all
        r'\.(\s|$)|'                        # git add . (as a standalone argument)
        r'\*(\s|$)'                         # git add * (as a standalone argument)
        r')', re.IGNORECASE
    )
    
    if git_add_pattern.search(normalized_cmd):
        reason = """DO NOT use 'git add -A', 'git add -a', 'git add --all', 'git add .' or 'git add *' as they add ALL files!
        
Instead, use one of these commands:
- 'git add -u' to stage all modified and deleted files (but not untracked)
- 'git add <specific-files>' to stage specific files you want
- 'gsuno' (alias for 'git status -uno') to see modified files only
- 'gcam "message"' to commit all modified files with a message

This restriction prevents accidentally staging unwanted files."""
        return True, reason
    
    # Also check for git commit -a without -m (which would open an editor)
    # Check if command has -a flag but no -m flag
    if re.search(r'^git\s+commit\s+', normalized_cmd):
        has_a_flag = re.search(r'-[a-zA-Z]*a[a-zA-Z]*', normalized_cmd)
        has_m_flag = re.search(r'-[a-zA-Z]*m[a-zA-Z]*', normalized_cmd)
        if has_a_flag and not has_m_flag:
            reason = """Avoid 'git commit -a' without a message flag. Use 'gcam "message"' instead, which is an alias for 'git commit -a -m'."""
            return True, reason
    
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
    
    should_block, reason = check_git_add_command(command)
    
    if should_block:
        print(json.dumps({
            "decision": "block",
            "reason": reason
        }))
    else:
        print(json.dumps({"decision": "approve"}))
    
    sys.exit(0)