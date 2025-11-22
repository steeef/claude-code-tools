# Node UI menu integration plan (concise)

## Goal

- Replace Textual/Python menus with Node-based UI for results table and menus
  while keeping Python backend logic intact and escapable back to results.

## Plan

- Define Node UI contract: entry command, stdin/stdout JSON schema, actions,
  escape semantics, parent-return flow, and error/fallback rules.
- Wire Python find/menu commands to launch Node UI when requested, pass search
  results + context, and handle callbacks for actions/escape paths.
- Provide IPC utilities, feature flag, and graceful fallback to current flows;
  ensure sidechain handling and trim/resume flows mirror existing logic.

## Testing

- Add pytest coverage for alt UI flag selection, IPC invocation contract, and
  escape-to-parent behavior; tests start failing before implementation.
- Validate Node UI shim integration paths once implemented; keep default flows
  unchanged without the flag.

## Deliverables

- Node UI launcher/integration code, documented IPC schema, updated find/menu
  entrypoints, and passing tests; only new files staged per repo rules.
