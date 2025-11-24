# Consolidate Commands Under aichat Group

## Issue

Too many flat commands exposed to users. Want to consolidate everything under
the `aichat` command group for cleaner, unified interface.

**Note:** This breaks backward compatibility but provides better UX.

## Current State vs Target

| Flat Commands (Remove) | aichat Subcommand (Keep) | Status |
|------------------------|-------------------------|--------|
| claude-continue, codex-continue | aichat continue | Exists (auto-detect) |
| find-claude-session | aichat find-claude | Exists |
| find-codex-session | aichat find-codex | Exists |
| find-session | aichat find | Exists |
| export-claude-session, export-claude-session | aichat export | **Needs auto-detect** |
| trim-session | aichat trim | Exists |
| smart-trim | aichat smart-trim | Exists |
| find-original-session | aichat find-original | Exists |
| find-derived-sessions | aichat find-derived | Exists |
| session-menu | aichat menu | Exists |

## Implementation Plan

1. **Add auto-detect to `aichat export`:**
   - Detect session type from file path or session ID
   - Route to appropriate export function
   - Support `--agent` flag to override

2. **Remove flat command entry points from pyproject.toml:**
   - Remove all flat command entries from `[project.scripts]`
   - Keep only `aichat` as main entry point
   - All functionality accessible via `aichat <subcommand>`

3. **Update documentation:**
   - README showing only `aichat` commands
   - Migration guide for users (optional)

## Breaking Change

Users relying on flat commands will need to switch to `aichat` subcommands:
- `claude-continue <session>` → `aichat continue <session>`
- `find-claude-session <keywords>` → `aichat find-claude <keywords>`
- etc.
