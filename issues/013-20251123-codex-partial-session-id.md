# Fix Codex Partial Session ID Matching in session-menu

## Issue

`aichat menu` command fails to find Codex sessions when using partial session
IDs that don't appear at the end of the filename.

Example:
- Session file: `rollout-2025-11-23T17-50-57-019ab2e9-cbdf-7a42-85e1-8df094473120.jsonl`
- Full ID: `019ab2e9-cbdf-7a42-85e1-8df094473120`
- Partial ID: `cbdf-7a42` (in middle of UUID)
- Command: `aichat menu cbdf-7a42` → Error: Session not found

## Root Cause

Inconsistent glob patterns between Claude and Codex session matching:
- Claude: `*{session_id}*.jsonl` - matches anywhere in filename
- Codex: `*{session_id}.jsonl` - only matches at end before .jsonl

## Solution

Changed Codex session matching to use same pattern as Claude:
`*{session_id}*.jsonl` to support partial ID matching anywhere in filename.

## File Changed

- `claude_code_tools/session_menu_cli.py` line 130
