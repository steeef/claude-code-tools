#!/usr/bin/env python3
import json
import sys
import subprocess

data = json.load(sys.stdin)
session_id = data.get('session_id', '')
prompt = data.get('prompt', '')
print("SESSION_ID IS ", session_id)

if prompt.startswith('smart-trim'):
    print("TRIGGERING SMART-TRIM")
    result = subprocess.run(
        ['/Users/pchalasani/.local/bin/smart-trim', session_id],
        capture_output=True,
        text=True
    )
    # Print output to stdout so it's shown to user (exit code 0)
    print(f"SMART-TRIM EXIT CODE: {result.returncode}")
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    sys.exit(0)

sys.exit(0)
