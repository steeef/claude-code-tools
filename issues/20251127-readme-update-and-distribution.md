# Issue Spec: README Update and Distribution Fixes for v0.3.0 Release

## Overview

The README has not kept pace with the significant Node UI implementation and new
features added in the `nodeui` branch. Additionally, there are distribution issues
that need to be addressed for `uv tool install` to work correctly with the Node UI.

## Distribution Issues (CRITICAL)

### Problem

The current `pyproject.toml` includes Node UI files but is missing dependencies:

**Currently Included:**
- `node_ui/menu.js`
- `node_ui/package.json`

**Missing:**
- `node_ui/action_config.js` - imported by menu.js, will cause runtime error
- Node dependencies (ink, react, chalk, figures, etc.) - in node_modules

### Impact

When users run `uv tool install claude-code-tools`:
1. The `node_ui/menu.js` will be installed
2. But `action_config.js` is missing - **immediate failure**
3. Even if fixed, `node_modules` is missing - `node menu.js` will fail

### Solution Options

**Option 1: Bundle JS with esbuild (Recommended)**
- Use esbuild to bundle menu.js + action_config.js + all node_modules into a single
  `menu.bundle.js`
- Add build step to Makefile: `npx esbuild menu.js --bundle --platform=node --outfile=menu.bundle.js`
- Update Python to call the bundled file
- Pros: Single file, no npm install needed
- Cons: Larger file (~500KB), need to rebuild on JS changes

**Option 2: Include node_modules in package**
- Add `node_ui/node_modules/**` to pyproject.toml includes
- Pros: Works immediately
- Cons: Package size increases significantly (~5MB+)

**Option 3: Post-install npm install**
- Add a post-install hook that runs `npm install` in node_ui directory
- Pros: Always fresh dependencies
- Cons: Requires npm at install time, may fail in restricted environments

**Option 4: Document manual step**
- Document that users need to run `cd $(python -c "import claude_code_tools; print(claude_code_tools.__path__[0])")/../node_ui && npm install`
- Pros: Simple
- Cons: Bad UX, users will forget

### Immediate Fix Required

~~At minimum, add `action_config.js` to pyproject.toml~~ **DONE** (commit `929e5c2`)

```toml
[tool.hatch.build]
include = [
    "claude_code_tools/**/*.py",
    "docs/*.md",
    "node_ui/menu.js",
    "node_ui/action_config.js",  # ADDED
    "node_ui/package.json",
    "claude_code_tools/action_rpc.py",
]
```

**Remaining**: Still need to address node_modules bundling (Option 1-4 above).

## README Updates Needed

### 1. New Node.js Interactive UI (MAJOR)

The README makes no mention that there's now a Node.js-based interactive UI that
is the **default**. This is a significant change.

**Add section after Quick Start:**

```markdown
## Interactive Node UI

The session management tools now feature a modern Node.js-based interactive UI
built with [Ink](https://github.com/vadimdemedes/ink) (React for CLIs).

**Requirements:**
- Node.js (v16+) - typically already installed if using Claude Code

**Features:**
- Smooth keyboard navigation with vim-like bindings
- Session preview with expand/collapse (Space key)
- Zoom mode for detailed session view (z key)
- Page navigation (u/d keys)
- Interactive find options with time filters
- Session lineage display for derived sessions

**Fallback:**
If you prefer the simpler Rich-based UI, use `--simple-ui` flag:
```bash
aichat find --simple-ui
aichat menu abc123 --simple-ui
```
```

### 2. New `aichat resume` Command

**Add new section after `aichat continue`:**

```markdown
## 🔄 aichat resume — quick session resumption

Quickly resume sessions for the current project without searching. Automatically
finds the most recent sessions for your current project and git branch.

### Usage

```bash
# Resume latest session (shows selection if multiple found)
aichat resume

# Resume only Claude sessions
aichat resume-claude

# Resume only Codex sessions
aichat resume-codex

# Resume specific session by ID
aichat resume abc123
```

### Features

- **Project-aware**: Finds sessions for your current working directory
- **Branch-aware**: Prioritizes sessions from your current git branch
- **Auto-selection**: If only one session matches, goes directly to resume options
- **Quick access**: No keyword search needed - just `aichat resume`
```

### 3. Interactive Find Options Menu

The README doesn't mention the new interactive options menu in find commands.

**Update `aichat find` section to include:**

```markdown
### Interactive Options Menu

When running `aichat find`, you'll see an interactive options menu:

- **Keywords**: Enter search terms (comma-separated)
- **Scope**: Toggle between current project and global search
- **Time filter**: Filter by recency (today, this week, this month, etc.)
- **Agent filter**: Search Claude only, Codex only, or both

Press Enter to search, or Esc to exit. After viewing results, press Esc to
return to the options menu and refine your search.
```

### 4. Session Preview Features

**Add to the Features sections:**

```markdown
### Session Preview & Navigation

- **Expand/Collapse**: Press `Space` to expand a session row and see the full
  last user message preview
- **Zoom Mode**: Press `z` to enter zoom mode where all sessions are expanded
  with dynamic height calculation
- **Page Navigation**: Use `u` (up) and `d` (down) to navigate by page in long
  lists
- **Number Selection**: Type a number and press Enter to select that session
  directly
```

### 5. Session Lineage Display

**Add to `aichat continue` or new section:**

```markdown
### Session Lineage

When continuing a session, you'll see the full lineage chain showing:
- Original session
- Any trimmed versions
- Any continued versions
- Exported chat logs

This helps you understand the history of a session before continuing it.
```

### 6. Query Session Feature (NEW)

**Add new section:**

```markdown
## 🔍 Query Session — Ask questions about past sessions

From the action menu (after selecting a session), choose "Query this session..."
to ask any question about a past session.

### How it works

1. Select a session from search results
2. Choose "Query this session..." from the action menu
3. Enter your question (or press Enter for default: "Summarize what was accomplished")
4. The session is exported and analyzed using the same agent (Claude or Codex)
5. View the response and press Esc to return

### Features

- **Parallel sub-agents**: Claude uses parallel sub-agents to efficiently explore
  large session logs without overloading context
- **Smart reading**: Codex uses efficient reading strategies for large files
- **Default export**: Session is exported to `exported-sessions/` in the project
  directory (reusable for future queries)
- **Any question**: Ask about what was done, summarize changes, find specific
  information, etc.

### Example questions

- "Summarize what was accomplished in this session"
- "What files were modified?"
- "What was the last task being worked on?"
- "Were there any errors or issues encountered?"
```

### 7. Update Screenshots

The current screenshots show the old Rich UI:
- `demos/find-claude-session.png`
- `demos/find-codex-session.png`

**Action:** Capture new screenshots of the Node UI and update references.

### 8. Update Requirements Section

```markdown
## Requirements

- Python 3.11+
- uv (for installation)
- **Node.js 16+** (for interactive UI - typically installed with Claude Code)
- tmux (for tmux-cli functionality)
- SOPS (for vault functionality)
```

### 9. Update Table of Contents

Add entries for:
- Node UI section
- `aichat resume` command
- Interactive find options
- Query session feature

### 10. Version Bump

The README header says "Breaking Change Notice (v0.3.0)" but pyproject.toml shows
version 0.2.7. Need to:
- Bump version to 0.3.0 in pyproject.toml
- Update __init__.py version
- Consider if this is truly a breaking change or just a feature release

## Commits Since Last README Update (39 commits)

Key feature commits to reference:

1. **Node UI Implementation**
   - `5ff79db`: Make Node UI default
   - `3fe98f5`: Initial Node alt UI
   - Various polish commits

2. **aichat resume**
   - `df7be80`: Add aichat resume command

3. **Find Options Menu**
   - `9c69a62`: Add interactive find options menu
   - `640a444`: Two-part find options menu

4. **Session Preview/Zoom**
   - `c2b1d24`: Space bar expand/collapse
   - `3a19420`: Zoom toggle
   - `ca2c32c`: Page navigation (u/d)
   - `6de5d12`: Dynamic row height in zoom

5. **Session Lineage**
   - `cb766a4`: Session lineage display

6. **Export/Trim Inference**
   - `8ac07d9`: Session inference for export/trim commands

7. **Query Session**
   - `033f461`: Add query session action to ask questions about past sessions

8. **Distribution Fix**
   - `929e5c2`: Add missing action_config.js to package distribution

## Priority Order

1. **CRITICAL**: ~~Fix distribution (add action_config.js)~~ DONE - still need bundling decision
2. **HIGH**: Document Node UI and requirements
3. **HIGH**: Document aichat resume command
4. **HIGH**: Document query session feature
5. **MEDIUM**: Document interactive features (find options, preview, zoom)
6. **MEDIUM**: Update screenshots
7. **LOW**: Minor documentation polish

## Testing Checklist

- [ ] `uv tool install .` works from fresh clone
- [ ] `aichat find` launches Node UI
- [ ] Node UI works without manual npm install
- [ ] All documented features match actual behavior
- [ ] Screenshots match current UI
- [ ] Query session action works for both Claude and Codex sessions
- [ ] `aichat resume` finds sessions for current project/branch
