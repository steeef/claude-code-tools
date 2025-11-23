# Node UI action RPC integration (path/copy/export)

Date: 2025-11-23
Status: Proposal / Ready to implement

## Goal

Keep non-launch actions (path/copy/export) inside the Node alt UI without duplicating
business logic. Use a small Python RPC/CLI entrypoint so both UIs call the same backend
code; Node handles presentation, Python handles the action.

## Scope

- Actions: show path, copy session file, export session.
- Targets: Claude + Codex sessions via existing action handlers.
- CLI flag compatibility: default (Rich) unchanged; `--altui` uses Node UI with RPC.
- No change to launch actions (resume/clone/continue/trim flows stay in Python UI).

## Design

- Add a Python CLI module `claude_code_tools.action_rpc`:
  - Input: JSON on stdin (action, session_id, agent, cwd/paths, extra args).
  - Output: JSON with `status`, `message`, `path` (for path/export), error text.
  - Reuse existing action functions; no user prompting inside RPC.
  - Non-interactive: copy/export take provided destinations; Node collects prompts.

- Node UI changes:
  - For path/copy/export, render a modal:
    - Path: display returned path + Enter=exit / Esc=back.
    - Copy/Export: prompt for destination; call RPC; show result/errs in modal.
  - Keep the existing post-action Enter=exit / Esc=back flow.

- Error handling:
  - RPC returns `status: error` + message; Node shows it inline and stays in the modal.
  - Timeouts surfaced with a friendly error.

## Plan

- [ ] Add `claude_code_tools/action_rpc.py` implementing stdin→stdout JSON actions.
- [ ] Wire `find_session` / `find_claude_session` / `find_codex_session` to pass
      session data to Node so RPC has needed fields (agent, paths, home dirs).
- [ ] Update Node UI modals for path/copy/export: collect dest (copy/export), call RPC,
      display output, then Enter=exit / Esc=back.
- [ ] Tests: unit test RPC for path/copy/export (happy/error). Adjust integration stub
      for new RPC call shape (or mock RPC in Node tests if added).
- [ ] Manual tmux verification: path/copy/export flows stay inside Node UI.

## Notes

- Keep default UI unchanged; `--altui` uses RPC-powered Node flow.
- Avoid touching launch/trim actions in this iteration.
