#!/usr/bin/env python3
import json
import subprocess
from pathlib import Path


def test_smart_trim_hook():
    """Test that the smart-trim hook parses JSON and invokes smart-trim."""
    hook_path = Path(__file__).parent.parent / "hooks" / "smart-trim-hook.py"

    # Construct JSON input matching UserPromptSubmit hook structure
    hook_input = {
        "session_id": "70534277-f3fa-458f-ade2-032c098159e5",
        "transcript_path": "/tmp/test.jsonl",
        "cwd": "/tmp",
        "permission_mode": "default",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "Please /smart-trim the session"
    }

    # Run the hook script with JSON input via stdin
    result = subprocess.run(
        [str(hook_path)],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True
    )

    # Verify the hook ran successfully
    assert result.returncode == 0

    # Verify session ID was captured (from the debug print)
    assert "70534277-f3fa-458f-ade2-032c098159e5" in result.stdout

    print(f"Hook output:\n{result.stdout}")
    if result.stderr:
        print(f"Hook stderr:\n{result.stderr}")


def test_smart_trim_hook_no_trigger():
    """Test that hook does nothing when /smart-trim is not in prompt."""
    hook_path = Path(__file__).parent.parent / "hooks" / "smart-trim-hook.py"

    hook_input = {
        "session_id": "70534277-f3fa-458f-ade2-032c098159e5",
        "transcript_path": "/tmp/test.jsonl",
        "cwd": "/tmp",
        "permission_mode": "default",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "Just a normal prompt without the trigger"
    }

    result = subprocess.run(
        [str(hook_path)],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True
    )

    # Should still succeed but not invoke smart-trim
    assert "SESSION_ID IS" in result.stdout
    # Should not have smart-trim output
    assert "smart-trim" not in result.stdout.lower() or "SESSION_ID" in result.stdout
