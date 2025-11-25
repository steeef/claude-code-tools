# Unify aichat trim and export with Node UI

## Issue 1: `aichat trim <sess>` should use Node UI submenu

Currently `aichat trim` does a direct trim. It should instead launch the Node UI
and show the same "Resume/trim" submenu options (resume, clone, suppress_resume,
smart_trim_resume, continue) that appear when selecting "Resume/trim session..."
from the main action menu.

**Key requirement**: Leverage existing Node UI code paths - no code duplication.

## Issue 2: `aichat export <sess>` uses old default path

Should use the new convention matching `action_config.js`'s `defaultExportPath()`:
- `exported-sessions/claude/{original-filename}.txt`
- `exported-sessions/codex/{original-filename}.txt`

**Key requirement**: Share the path logic with Node UI, don't duplicate.
