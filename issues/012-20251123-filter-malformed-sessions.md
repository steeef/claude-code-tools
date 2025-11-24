# Filter Malformed Claude Code Sessions from Search Results

## Issue

Sessions with file-history-snapshot as first line (instead of proper metadata)
appear in search results but cannot be resumed. These are corrupted/malformed
sessions from old trimming operations that stripped critical metadata.

## Example

Session file with only file-history-snapshots:
- Missing sessionId in first line
- First line has type: "file-history-snapshot"
- Cannot be resumed by Claude Code

## Solution

Added `is_malformed_session()` function to detect sessions where:
- First line is type "file-history-snapshot"
- First line missing sessionId field
- Empty or unparseable first line

Filter these out in find-claude-session and find-session (unified finder).
Codex sessions unaffected (this is Claude Code-specific issue).

## Implementation

- `claude_code_tools/find_claude_session.py`: Added is_malformed_session()
- `claude_code_tools/find_session.py`: Import and use for Claude sessions only
