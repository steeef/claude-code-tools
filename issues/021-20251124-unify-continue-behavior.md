# Issue #021: Unify Continue Behavior Across All Entry Points

**Date:** 2025-11-24
**Status:** Completed
**Priority:** Medium (UX consistency + code consolidation)

## Problem

There are three ways to continue a session, but they offer inconsistent options:

1. **`aichat continue <session_id>`** - Goes directly to continuation without
   offering agent choice or custom prompt options
2. **`aichat menu <session_id> -> continue`** - Offers these options
3. **`aichat find* -> continue`** - Offers these options (via action menu)

The `aichat continue` command is missing the interactive prompts for:

- Agent choice (Claude vs Codex)
- Custom prompt to prepend to the continuation

## Requirements

### 1. Consistent Options Across All Paths

All three entry points should offer the same interactive prompts:

- **Agent choice**: Which agent to use for analyzing the session chain and
  creating the new continuation session (Claude or Codex)
- **Custom prompt**: Optional instructions to prepend to the continuation
  (e.g., "focus only on the latest session", "ignore the refactoring work")

### 2. Timing of Prompts

The options should be presented in this order:

1. Resolve session (find the session file)
2. **Trace and display lineage** (show the chain of continued sessions)
3. **Present options** (agent choice, custom prompt) - user can make informed
   decisions based on seeing the lineage
4. Create new coding agent session with the chosen options

This timing is important because the user may want to modify their prompt based
on the lineage they see (e.g., "there are 5 sessions in the chain, only look at
the last 2").

### 3. Code Consolidation

Create shared helper functions to avoid code duplication between:

- `aichat continue`
- `aichat menu -> continue`
- `aichat find* -> continue`

The shared code should handle:

- Displaying lineage
- Prompting for agent choice
- Prompting for custom prompt
- Executing the continuation with chosen options

## Implementation Notes

- Look at existing implementation in `find_session.py` and `session_menu.py`
  for how agent choice and custom prompt are currently handled
- The helper function(s) should be placed in an appropriate shared module
  (likely `session_utils.py` or `session_menu.py`)
- Ensure backward compatibility: if `--prompt` is passed via CLI, skip the
  interactive prompt for custom instructions

## Files Likely Affected

- `claude_code_tools/continue_session.py` (or wherever `aichat continue` lives)
- `claude_code_tools/session_menu.py`
- `claude_code_tools/session_utils.py`
- `claude_code_tools/find_session.py`
- `claude_code_tools/find_claude_session.py`
- `claude_code_tools/find_codex_session.py`
