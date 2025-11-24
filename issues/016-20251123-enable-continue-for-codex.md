# Enable Continue Command for Codex Sessions

## Issue

Continue command currently disabled for Codex sessions, but should work.

## Solution

- Enable "continue" action for Codex sessions
- Add warning: "Started with Codex session, resuming as Claude Code session"
- Works because: export → Claude Code summarization → resume as Claude Code

## Files

- session_menu_cli.py: Remove restriction, add warning in execute_action
