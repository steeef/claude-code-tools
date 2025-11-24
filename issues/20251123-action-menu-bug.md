# Issue #20251123-action-menu-bug: Action menu overlaps/blank screens in Node alt UI

## Summary

Current behavior **before latest fix**: When running `aichat find-claude --altui -n 20` and selecting a row, the action menu rendered *below* the results list; the “Actions …” header could share a line with the annotation legend. The list stayed visible instead of being replaced.

Update 2025-11-24: Implemented a TTY clear on view switches in `App` and clamped the current index. Manual test via `tmux-cli` on pane 1 shows the action view now fully replaces the list (no overlap) and the back-to-results flow works. Keep this issue open until another run confirms across datasets.

Expected: Selecting a session should replace the results list with the action view (single screen). No overlap, no legend collision, and no need for manual clears.

## Context / Code structure

- Node UI entrypoint: `node_ui/menu.js` (Ink/React, no build step). Primary components:
  - `ResultsView`: renders sessions list, legend, scope line, handles selection.
  - `ActionView`, `ResumeView`, `TrimForm`, `NonLaunchView`: action/resume/trim/non-launch modals.
  - `App`: state machine (`screen` = results/action/resume/trim/nonlaunch), switches views.
- Python launchers pass payload via temp JSON: `claude_code_tools/node_menu_ui.py` → `_write_payload` → Node.
- Action handler (Python) now uses RPC for non-launch actions: `claude_code_tools/action_rpc.py` called by Node.

## Recent changes (may be relevant)

- Added column alignment and legends in `ResultsView`.
- Added numeric jumps and long labels in action/resume menus.
- Attempted to “replace” the list by clearing the screen when leaving results; led to blank screens.
- Removed/re-added `clearScreen` in various places; current state still problematic for large lists.

## Repro steps

1. In tmux pane 1 (different repo), run: `aichat find-claude --altui -n 20`
2. Select row 9 (e.g., type `9` + Enter).
3. Observe: action menu either appears below the list with header on the legend line, or screen blanks after selection.

## Suspected root cause

- Ink renders `ResultsView` and then `ActionView` without clearing or re-rendering the root; view switching logic still returns separate components but doesn’t ensure a fresh render or terminal clear. When list scrolls (`-n 20`), output remains in buffer so action UI prints after it.
- Attempts to clear the terminal on screen change caused blank output—needs a safe Ink-friendly clear (e.g., render a single top-level container, maybe `App` should render only one child and not rely on manual `stdout` clears).

## Files to inspect

- `node_ui/menu.js`: view switching in `App` (bottom of file), `ResultsView` selection handling, any `clearScreen` attempts.
- `claude_code_tools/node_menu_ui.py`: payload fields; ensure no accidental double-runs.
- `claude_code_tools/action_rpc.py`: only for context; likely not the cause.

## Related issues (for context/history)

- `issues/20251120-textual-session-menu.md` — original alt UI requirements.
- `issues/20251122-node-ui-fixes.md` — prior fixes for list display/annotations.
- `issues/20251123-node-ui-action-rpc.md` — non-launch actions via RPC.
- `issues/20251123-4-further-nodeui-fixes.md` — alignment, legends, numeric actions.

## Desired behavior

- Selecting a session should replace the results view with the action (or resume/trim/nonlaunch) view. No prior content visible. No blank screens.
- Works with long lists (e.g., `-n 20`) that scroll in the list view.

## Notes

- Avoid manual terminal clears that blank Ink output; prefer rendering a single active view.
- Keep numeric jumps and alignment intact; don’t regress current legend/scope lines.
