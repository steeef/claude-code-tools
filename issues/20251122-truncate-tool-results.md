# Truncate Tool Results Instead of Replacing

## Current Behavior

Tool results exceeding threshold are completely replaced with placeholder:
`[Results from bash tool suppressed - original content was 5,000 characters]`

## Desired Behavior

Truncate tool results to threshold length, preserving first N characters.
Example: For threshold=500, keep first 500 chars and append truncation notice.

## Implementation

Modify `trim_session_claude.py` and `trim_session_codex.py` to truncate
content instead of replacing with placeholder.
