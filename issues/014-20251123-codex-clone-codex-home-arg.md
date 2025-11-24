# Fix Codex clone_session to Accept codex_home Argument

## Issue

When cloning a Codex session via `aichat menu`, get TypeError:
```
TypeError: clone_session() got an unexpected keyword argument 'codex_home'
```

## Root Cause

In `session_menu_cli.py` line 296, when cloning Codex sessions:
```python
clone_session(str(session_file), shell_mode=False, codex_home=codex_home)
```

But `find_codex_session.clone_session()` doesn't accept `codex_home` parameter.

## Solution

Update `find_codex_session.clone_session()` to accept optional `codex_home`
parameter, consistent with Claude's clone_session signature.

## Files to Modify

- `claude_code_tools/find_codex_session.py` - Add codex_home parameter to
  clone_session()
- `tests/` - Add test to verify clone_session accepts codex_home
