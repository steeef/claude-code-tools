#!/usr/bin/env python3
"""
Verify that all session IDs in JSON output from `aichat search --json` are unique.

Usage:
    aichat search "query" --json | python3 scripts/verify_unique_session_ids.py
    aichat search "query" --json -n 100 | python3 scripts/verify_unique_session_ids.py
"""

import json
import sys
from collections import Counter


def main():
    # Read JSONL (one JSON object per line)
    items = []
    for line_num, line in enumerate(sys.stdin, 1):
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON on line {line_num}: {e}", file=sys.stderr)
            return 1

    if not items:
        print("No input received")
        return 0

    session_ids = [item.get("session_id") for item in items if "session_id" in item]

    if not session_ids:
        print("No session_id fields found in input")
        return 0

    counts = Counter(session_ids)
    duplicates = {sid: count for sid, count in counts.items() if count > 1}

    if duplicates:
        print(f"FAIL: {len(duplicates)} duplicate session IDs found:")
        for sid, count in sorted(duplicates.items(), key=lambda x: -x[1]):
            print(f"  {sid}: {count} occurrences")
        return 1
    else:
        print(f"OK: {len(session_ids)} unique session IDs")
        return 0


if __name__ == "__main__":
    sys.exit(main())
