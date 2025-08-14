#!/usr/bin/env python3
"""
Hook to protect .env files from being read or searched.
Blocks commands that would expose .env contents and suggests safer alternatives.
"""
import re

def check_env_file_access(command):
    """
    Check if a command attempts to read or search .env files.
    Returns tuple: (should_block: bool, reason: str or None)
    """
    # Normalize the command
    normalized_cmd = ' '.join(command.strip().split())
    
    # Safe patterns that should be allowed (only show keys, not values)
    # These patterns only extract key names, not values
    if ("grep -o '^[^#][^=]*' .env" in normalized_cmd or
        "grep -o \"^[^#][^=]*\" .env" in normalized_cmd or
        re.search(r"grep\s+-q\s+['\"]?\^[A-Z_]+=", normalized_cmd)):
        return False, None  # Allow safe patterns
    
    # Patterns that indicate reading or searching .env files
    env_patterns = [
        # Direct file reading
        r'\bcat\s+.*\.env\b',
        r'\bless\s+.*\.env\b',
        r'\bmore\s+.*\.env\b',
        r'\bhead\s+.*\.env\b',
        r'\btail\s+.*\.env\b',
        r'\bnano\s+.*\.env\b',
        r'\bvi\s+.*\.env\b',
        r'\bvim\s+.*\.env\b',
        r'\bemacs\s+.*\.env\b',
        r'\bcode\s+.*\.env\b',
        
        # Searching/grepping .env files
        r'\bgrep\s+.*\.env\b',
        r'\bgrep\s+.*\s+\.env\b',
        r'\brg\s+.*\.env\b',
        r'\brg\s+.*\s+\.env\b',
        r'\bag\s+.*\.env\b',
        r'\back\s+.*\.env\b',
        r'\bfind\s+.*-name\s+["\']?\.env',
        
        # Other ways to expose .env contents
        r'\becho\s+.*\$\(.*cat\s+.*\.env.*\)',
        r'\bprintf\s+.*\$\(.*cat\s+.*\.env.*\)',
        
        # Also check for patterns without the dot (like "env" file)
        r'\bcat\s+["\']?env["\']?\s*$',
        r'\bcat\s+["\']?env["\']?\s*[;&|]',
        r'\bless\s+["\']?env["\']?\s*$',
        r'\bless\s+["\']?env["\']?\s*[;&|]',
    ]
    
    # Check if any pattern matches
    for pattern in env_patterns:
        if re.search(pattern, normalized_cmd, re.IGNORECASE):
            reason_text = (
                "Blocked: Direct access to .env files is not allowed for security reasons.\n\n"
                "Instead, use one of these safer alternatives:\n"
                "- To see which environment variables are defined (keys only):\n"
                "  `grep -o '^[^#][^=]*' .env | sort`\n"
                "- Or create a custom command/alias like:\n"
                "  `alias envkeys='grep -o \"^[^#][^=]*\" .env | sort'`\n"
                "- To check if a specific key exists:\n"
                "  `grep -q '^KEY_NAME=' .env && echo 'Key exists' || echo 'Key not found'`\n\n"
                "If you need to work with actual values, consider:\n"
                "- Manually checking the file outside of Claude Code\n"
                "- Using environment variables that are already loaded"
            )
            return True, reason_text
    
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
    
    should_block, reason = check_env_file_access(command)
    
    if should_block:
        print(json.dumps({
            "decision": "block",
            "reason": reason
        }, ensure_ascii=False))
    else:
        print(json.dumps({"decision": "approve"}))
    
    sys.exit(0)