# tmux-cli Pane Targeting Bug

## Issue

tmux-cli sends commands to panes in the currently active window instead of
panes in the window where tmux-cli is being executed from.

## Expected Behavior

When a process in window 1 runs `tmux-cli` to send to pane 4, it should target
pane 4 in window 1, regardless of which window is currently active/visible.

## Current Buggy Behavior

If user is viewing window 3, tmux-cli from window 1 incorrectly targets pane 4
in window 3 instead of pane 4 in window 1.

## Fix

Modified `list_panes()` in `tmux_cli_controller.py:217` to use
`get_current_window_id()` when no explicit target is provided. This ensures
pane indices are resolved within the window where the command is executed
(via `TMUX_PANE` environment variable), not the currently active window.
