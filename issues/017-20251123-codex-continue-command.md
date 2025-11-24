# Implement codex-continue Command

## Issue

Create `codex-continue` command analogous to `claude-continue` that works
entirely in Codex non-interactive mode.

## Approach

1. Use `codex exec --json` to run summarization prompt programmatically
2. Extract `thread_id` from JSON stream using `jq`
3. Use `codex exec resume <SESSION_ID>` to continue in new session
4. Follow same pattern as `claude-continue`:
   - Export session to text
   - Run summarization prompt
   - Start fresh session with summary as context

## Implementation Plan

1. Create `claude_code_tools/codex_continue.py`:
   - `codex_continue()` function similar to `claude_continue()`
   - Export Codex session to text file
   - Use `codex exec --json` with summarization prompt
   - Parse JSON stream with `jq` to extract thread_id
   - Resume with `codex exec resume <thread_id>`

2. Create CLI command `codex-continue`:
   - Entry point in `pyproject.toml`
   - Takes session file path or session ID
   - Optional `--prompt` flag for custom summarization

3. Add to session menu for Codex sessions

## Reference

- https://developers.openai.com/codex/sdk#using-codex-cli-programmatically
- `claude_code_tools/claude_continue.py` for pattern
