# Fix Codex clone_session Call Missing Arguments

## Issue

After adding codex_home parameter, clone_session still fails because
session_menu_cli.py doesn't pass required session_id and cwd arguments.

Error:
```
TypeError: clone_session() missing 2 required positional arguments: 'session_id' and 'cwd'
```

## Root Cause

In session_menu_cli.py line 293-295, calling clone_session with:
```python
clone_session(str(session_file), shell_mode=False, codex_home=codex_home)
```

But function signature requires:
```python
def clone_session(file_path: str, session_id: str, cwd: str, shell_mode: bool = False, codex_home: Optional[str] = None)
```

Missing: session_id and cwd arguments

## Solution

Extract session_id and cwd (project_path) and pass them to clone_session,
matching how Claude sessions are handled on lines 288-290.

## Files to Fix

- session_menu_cli.py line 293-295: Pass session_id and project_path
- tests/test_codex_clone_codex_home.py: Improve test to match real usage
