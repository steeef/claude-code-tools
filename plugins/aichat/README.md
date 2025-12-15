# aichat

Provides the `session-searcher` subagent so Claude Code can search past sessions using
the `aichat search` command.

## What it does

This plugin adds a subagent that Claude auto-invokes when you ask about previous work.
It searches through code-agent session JSONL files (from Claude Code or Codex CLI) and
returns concise summaries without polluting main context.

## Usage

Just ask naturally:
- "What did we work on yesterday?"
- "Find sessions where we discussed authentication"
- "What design decisions did we make for the API?"

Claude will automatically invoke the `session-searcher` subagent.

### Manual CLI usage

The `aichat search` command with `--json` flag returns JSONL-formatted results:

Example - find and examine the top matching session:
```bash
# Get the file path of the top matching session
aichat search --json "authentication bug fix" | head -1 | jq -r '.file_path'

# Then read/search through that session JSONL to understand what was done
```

Run `aichat search --help` to see all available options.

### JSON output fields

When using `--json`, each result line contains:

- `session_id` - unique session identifier
- `agent` - claude or codex
- `project`, `branch`, `cwd` - project context
- `lines` - number of lines in session
- `created`, `modified` - timestamps
- `first_msg`, `last_msg` - first and last user messages
- `file_path` - path to session file
- `snippet` - matching text snippet

## Installation

This plugin requires the `claude-code-tools` and `aichat-search` packages:

```bash
uv tool install claude-code-tools   # Python package
cargo install aichat-search         # Rust search TUI
```

Prerequisites:

- Node.js 16+ - for action menus (resume, export, etc.)
- Rust/Cargo - for aichat search

If you don't have uv or cargo:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh                # uv
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh # Rust
```
