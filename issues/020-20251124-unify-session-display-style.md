# Issue #020: Unify Session Display Style Across Find Commands

**Date:** 2025-11-24
**Status:** Open
**Priority:** Low (cosmetic consistency)

## Problem

Inconsistent session annotation and styling between `aichat find` and the individual find commands:

1. **Session annotations**: `find-claude` and `find-codex` use old `*` notation for trimmed sessions, while `find` uses modern `(t)`, `(c)`, `(sub)` notation
2. **Session ID color**: `find-codex` uses `yellow` for session ID column, while `find` and `find-claude` use `dim` (gray)

## Fix Locations

**claude_code_tools/find_claude_session.py:592**
- Change: `session_id_display += " *"` → `session_id_display += " (t)"`
- Update footnote to match `find` command style

**claude_code_tools/find_codex_session.py:370**
- Change: `style="yellow"` → `style="dim"`

**claude_code_tools/find_codex_session.py:381, 407**
- Change: `session_id_display += " *"` → `session_id_display += " (t)"`
- Update footnote to match `find` command style

## Expected Result

All three commands (`find`, `find-claude`, `find-codex`) display sessions with identical styling and notation.
