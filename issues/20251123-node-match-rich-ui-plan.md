# Plan: Align Node alt UI with Rich UI (issue 20251123-node-match-rich-ui)

## Goals

- Make Node alt UI action menus mirror the rich UI: ordering, grouping, hints, prompts, defaults.
- Remove divergent logic between Node and rich UI by reusing shared data/behavior where possible.

## Refactor strategy (reduce duplication)

- Introduce a shared action metadata module (JS or JSON) consumed by both Node UI and rich UI (or sourced from existing rich UI config if accessible).
- Centralize: action order, grouping (non-launch vs launch), labels, hints, default destination rules.
- Update Node UI to render from this shared metadata instead of hardcoded arrays in `node_ui/menu.js`.

## Implementation steps

1) **Study rich UI sources**: locate action menu definitions, prompts, and default-path handling in the rich UI (likely React components/config). Record exact order, copy/export prompts, and default path rule.
2) **Extract shared action config**: create `node_ui/action_config.js` (or reuse existing rich UI config if importable) exporting ordered actions with fields: `value`, `label`, `group` (`nonlaunch`/`launch`), `hint`, `requiresPath`, `defaultPathProvider` (or flag to use default when blank).
3) **Wire Node UI to config**: in `node_ui/menu.js`, replace `mainActions` with data from the shared config; render grouped sections matching rich UI order; keep sidechain filter for non-launch-only where applicable.
4) **Copy/Export prompt UX**: in `NonLaunchView`, show a clear input affordance (e.g., `Destination: <current>` with caret indicator) and explicit hint text mirroring rich UI ("Leave blank to use default .txt path"). Ensure long paths scroll/extend.
5) **Blank destination handling**: on Export and Copy, if user submits empty input, resolve to the default path (same logic as rich UI). Implement via shared `defaultPathProvider` to avoid divergence.
6) **Tests**: add/extend integration tests to cover: grouped action order, non-launch vs launch grouping, blank export path uses default, prompts include rich UI hints, and copy/export input echo. Use pytest harness invoking Node alt UI with canned payloads.
7) **Manual verification**: run `aichat find-claude --altui -n 20` in tmux pane 1; validate grouped menu layout, path prompts, blank-path default behavior, sidechain filtering, back navigation.

## Notes / Open questions

- If direct reuse of rich UI modules is feasible, prefer import; otherwise mirror the config in one shared file and reference from both UIs to prevent future drift.
- Ensure line width stays within 88 chars where applicable and Ink rendering remains readable in narrow terminals.
