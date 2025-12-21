# claude-code-tools

[![claude-code-tools](https://img.shields.io/github/v/release/pchalasani/claude-code-tools?filter=v*&label=claude-code-tools&color=blue)](https://pypi.org/project/claude-code-tools/)
[![aichat-search](https://img.shields.io/github/v/release/pchalasani/claude-code-tools?filter=rust-v*&label=aichat-search&color=orange)](https://github.com/pchalasani/claude-code-tools/releases?q=rust)

A collection of practical tools, hooks, and utilities for enhancing Claude Code
and other CLI coding agents.

<a id="quick-start"></a>
## 🚀 Quick Start

```bash
uv tool install claude-code-tools   # Python package (includes Node.js UI)
```

**Install the search TUI** (one of these):

- **Homebrew** (macOS/Linux): `brew install pchalasani/tap/aichat-search`
- **Cargo**: `cargo install aichat-search` (compiles from source, takes ~5-6 min)
- **Pre-built binary**: Download from [Releases](https://github.com/pchalasani/claude-code-tools/releases) (look for `rust-v*` releases)

**Prerequisites:**

- **Node.js 16+** — Required for `aichat` action menus (resume, export, etc.)

That's it! The Python package includes pre-installed Node.js dependencies, so no
`npm install` is needed.

Without `aichat-search`, the search command won't be available, but other
`aichat` commands still work.

### What You Get

Four commands are installed:

| Command | Description |
|---------|-------------|
| [`aichat`](#aichat-session-management) | Session management for Claude Code and Codex (find, resume, export, trim, query) |
| [`tmux-cli`](#tmux-cli-terminal-automation) | Terminal automation for AI agents ("Playwright for terminals") |
| [`vault`](#vault) | Encrypted .env backup and sync |
| [`env-safe`](#env-safe) | Safe .env inspection without exposing values |

### Claude Code Plugins

This repo also provides plugins for the
[Claude Code marketplace](https://github.com/anthropics/claude-code-plugins):

| Plugin | Description |
|--------|-------------|
| `aichat` | Session management: hooks (`>resume`), commands, skills, agents |
| `tmux-cli` | Terminal automation skill for controlling other tmux panes |
| `workflow` | Work logging and code walk-through skills |
| `safety-hooks` | Prevent destructive git/docker/rm commands |

**Install the plugins:**

Add the marketplace via the `claude plugin` CLI:
```bash
claude plugin marketplace add pchalasani/claude-code-tools
```
This creates the `cctools-plugins` plugin group. From this, you can add the following 
plugins:
```bash
claude plugin install "aichat@cctools-plugins"
claude plugin install "tmux-cli@cctools-plugins"
claude plugin install "workflow@cctools-plugins"
claude plugin install "safety-hooks@cctools-plugins"
```

These can also be installed via the built-in `/plugin` command which launches a TUI.


---

## ⚠️ Breaking Change (v1.0)

All session tools are now under `aichat`. Use `aichat search` instead of
`find-claude-session`/`find-codex-session`, and similarly for other commands.

---

## Table of Contents

- [🚀 Quick Start](#quick-start)
- [💬 aichat — Session Management](#aichat-session-management)
- [🎮 tmux-cli — Terminal Automation](#tmux-cli-terminal-automation)
- [🚀 lmsh (Experimental) — natural language shell](#lmsh-experimental)
- [📊 Status Line](#status-line)
- [🔐 Utilities](#utilities)
- [🛡️ Claude Code Safety Hooks](#claude-code-safety-hooks)
- [🤖 Using with Alternative LLM Providers](#using-claude-code-with-open-weight-anthropic-api-compatible-llm-providers)
- [📚 Documentation](#documentation)
- [📋 Requirements](#requirements)
- [🛠️ Development](#development)
- [📄 License](#license)


<a id="aichat-session-management"></a>
# 💬 aichat — Session Management

### The Problem: Running Out of Context

You're deep into a Claude Code or Codex session, making good progress, when you
see the dreaded warning about the context window getting full. What do you do?

**Compaction is lossy.** The built-in compaction summarizes your conversation to
free up space, but it **loses detailed information permanently**—code snippets,
debugging steps, design decisions—gone with no way to recover them
(You could *fork* the session and *then* compact, but this new session still has no link
to the original session).

### The Solution: Manage Context with Lineage

`aichat` gives you three strategies for managing context—**trim**, **smart
trim**, and **rollover**—all of which preserve a **lineage chain** linking back
to parent sessions. Unlike compaction, nothing is lost:

- **Full parent session preserved** — complete history remains accessible, since 
parent session file paths are added at the end of the first user message in the session.
- **Lineage chain** — file paths of all ancestor sessions (jsonl files).
- **On-demand retrieval** — the agent can look up any past session in the lineage chain 
to recover  specific details when needed, or when prompted by the user, e.g. "in the linked prior chats, look up how we figured out the node-ui to Python communication".

```bash
aichat resume          # Find latest session and choose a strategy
aichat search "topic"  # Or search first, then pick resume action
```

See [Resume Options](#resume-options--managing-context) for details on each
strategy.

---

The `aichat` command is your unified interface for managing Claude Code and Codex
sessions. Search, resume, export, and navigate your AI conversation history.

**Key principles:**

- **Session ID optional:** Commands find the latest sessions for your current
  project/branch when no ID is provided.
- **No extra API costs:** Features using AI agents (smart-trim, query, rollover)
  use your existing Claude or Codex subscription.

```bash
aichat --help              # See all subcommands
aichat <subcommand> --help # Help for specific subcommand
```

---

## aichat search — Find and Select Sessions

The primary entry point for session management. Uses Tantivy (Rust full-text
search) to provide fast search across all your Claude and Codex sessions.

Here's what it looks like:

![aichat search demo](demos/aichat-search-asciinema.gif)

```bash
aichat search                      # Interactive TUI for current project
aichat search "langroid MCP"       # Pre-fill search query
aichat search -g                   # Global search (all projects)
aichat search --json -g "error"    # JSONL output for AI agents
```

**How it works:**

- **Auto-indexing:** Sessions are automatically indexed on startup—no manual
  export or build steps needed.
- **Self-explanatory TUI:** Filter by session type, agent, date range, and more.
  All options are visible in the UI.
- **CLI options:** All search options are available as command-line arguments. Run
  `aichat search --help` for details.
- **JSON mode:** Use `--json` for JSONL output that AI agents can process with
  `jq` or other tools. Add `--by-time` to sort by last-modified time instead of
  relevance.

**Session type filters:**

By default, search includes original, trimmed, and rollover sessions (but not
sub-agents). Use flags to include only specific types:

```bash
aichat search                           # Default: original + trimmed + rollover
aichat search --sub-agent               # Only sub-agents
aichat search --original                # Only original sessions
aichat search --original --sub-agent    # Only originals and sub-agents
aichat search --trimmed --rollover      # Only trimmed and rollover
```

The flags are: `--original`, `--trimmed`, `--rollover`, `--sub-agent`

When ANY type flag is specified, ONLY those types are included. When no type
flags are specified, defaults apply (original + trimmed + rollover).

---

## Conceptual Flow: Search → Select → Actions

The typical workflow:

1. **Search** — Use `aichat search` to find sessions by keywords, date, or filters
2. **Select** — Choose a session from the results
3. **Actions** — Perform operations on the selected session

After selecting a session, you see the **actions menu**. This is equivalent to
running `aichat <session-id>` or `aichat menu <session-id>` directly.

**Session ID formats** (accepted by most commands):

- Full path: `~/.claude/projects/.../abc123.jsonl`
- Full ID: `abc123-def456-789-...`
- Partial ID: `abc123` (if unique)

---

## Session Actions

After selecting a session, the action menu offers:

- **Show path / Copy / Export** — File operations
- **Query** — Ask questions about the session using an AI agent
- **Resume options** — Various strategies for continuing work (see below)

---

## Resume Options — Managing Context

### Finding Your Session

Three ways to get to the resume menu:

```bash
# 1. You know the session ID (from /status in your chat)
aichat resume abc123-def456

# 2. You don't know the ID - auto-find latest for this project
aichat resume

# 3. You need to search - find by keywords, then pick resume action
aichat search "langroid agent"
```

### Running Out of Context

When context fills up, you have three strategies. All preserve **session
lineage** - a chain of links back to the original session that the agent can
reference at any time.

**1. Trim + Resume**

Truncates large tool call results and assistant messages to free up space.
Quick and deterministic - you control what gets cut.

**2. Smart Trim + Resume**

Uses an AI agent to analyze the session and strategically identify what can
be safely truncated. More intelligent but adds processing time.

**3. Rollover**

Hands off work to a fresh session with a summary of the current task. The new
session starts with maximum context available while maintaining full access
to the parent session's details.

### Why Lineage Matters

Unlike built-in compaction (which permanently loses information), all three
strategies preserve the complete parent session. The new/resumed session
receives:

- **Lineage chain** — file paths of all ancestor sessions back to the original
- **On-demand retrieval** — the agent can look up any past session to recover
  specific details when needed

```
Original Session (abc123)
 └─► Trimmed/Rollover 1 (def456)
      └─► Trimmed/Rollover 2 (ghi789)
           └─► ... chain continues
```

### How Rollover Works

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ROLLOVER: Continue work in fresh context while preserving full history    │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────┐
  │  aichat resume          │  ◄── User triggers rollover of session ghi789
  │  or aichat search       │
  └───────────┬─────────────┘
              │
              ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │  1. TRACE LINEAGE of ghi789                                          │
  │     Follow continue_metadata.parent_session_file pointers backwards  │
  │                                                                      │
  │     ghi789.jsonl ──► def456.jsonl ──► abc123.jsonl (original)        │
  └──────────────────────────────────────────────────────────────────────┘
              │
              ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │  2. BUILD PROMPT                                                     │
  │     • Chronological list of all ancestor session files               │
  │     • Instructions to extract context                                │
  │     • Optional: summary of work extracted by another agent           │
  └──────────────────────────────────────────────────────────────────────┘
              │
              ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │  3. CREATE NEW INTERACTIVE SESSION (jkl012)                          │
  │                                                                      │
  │     • Work summary already present in prompt, OR                     │
  │     • User can ask agent to recover specific parts of prior work     │
  │       (using session-search skill or session-searcher sub-agent)     │
  └──────────────────────────────────────────────────────────────────────┘
              │
              ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │  4. INJECT METADATA (first line of jkl012.jsonl)                     │
  │                                                                      │
  │     {                                                                │
  │       "continue_metadata": {                                         │
  │         "parent_session_file": "/path/to/ghi789.jsonl",              │
  │         "parent_session_id": "ghi789-...",                           │
  │         "continued_at": "2025-12-19T..."                             │
  │       }                                                              │
  │     }                                                                │
  └──────────────────────────────────────────────────────────────────────┘
              │
              ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │  5. RESUME INTERACTIVELY                                             │
  │     claude --resume jkl012  ◄── Fresh context, full history access   │
  └──────────────────────────────────────────────────────────────────────┘


  RESULT: Linked chain with on-demand context retrieval
  ═══════════════════════════════════════════════════════

    abc123.jsonl ◄─── def456.jsonl ◄─── ghi789.jsonl ◄─── jkl012.jsonl
    (original)        (trimmed)         (rollover)        (NEW SESSION)
         │                 │                 │                  │
         └─────────────────┴─────────────────┴──────────────────┘
         Agent can read any ancestor on demand
         (using session-search skill or session-searcher sub-agent)
```

### Agent Access to History

Your agent can search across all historical sessions using the JSON output
mode:

```bash
aichat search --json -g "error handling"  # Returns JSONL for programmatic use
aichat search --json --by-time            # Sort by last-modified time
```
<!--CLAUDE - mention that there is a plugin `session-search` that provides a skill
called `session-search` that shows Claude Code how to use `aichat search`
to search past sessions.
-->

This enables agents to find and retrieve context from any past session in the
lineage, either on their own initiative or when you prompt them to look up
historical context.

---

## All Subcommands

| Command | Description |
|---------|-------------|
| `aichat search [query]` | Full-text search TUI across all sessions |
| `aichat menu [session]` | Interactive action menu for a session |
| `aichat resume [session]` | Resume options (resume, clone, trim, rollover) |
| `aichat info [session]` | Show session metadata, path, and lineage |
| `aichat export [session]` | Export session to text |
| `aichat copy [session]` | Copy session file to new location |
| `aichat query [session] [question]` | Query session with AI |
| `aichat clone [session]` | Clone session and resume the clone |
| `aichat rollover [session]` | Hand off to fresh session with lineage |
| `aichat lineage [session]` | Show parent lineage chain |
| `aichat trim [session]` | Trim large tool outputs |
| `aichat smart-trim [session]` | AI-powered trimming (EXPERIMENTAL) |
| `aichat delete [session]` | Delete with confirmation |
| `aichat find-original [session]` | Trace back to original session |
| `aichat find-derived [session]` | Find all derived sessions |

**Index management:**

| Command | Description |
|---------|-------------|
| `aichat build-index` | Manually rebuild the search index |
| `aichat clear-index` | Clear the index for a fresh rebuild |
| `aichat index-stats` | Show index statistics and reconciliation |

The search index is powered by [Tantivy](https://github.com/quickwit-oss/tantivy)
(Rust full-text search). You typically don't need to manage it manually:

- **Auto-updates**: Index updates incrementally on every `aichat` command
- **Version rebuilds**: Index rebuilds automatically when the tool version changes
- **Manual rebuild**: Use `aichat clear-index && aichat build-index` if needed

Run `aichat <command> --help` for options

---

### Quick Resume from Within Claude Code

If you've installed the `aichat` plugin, you get a convenient hook for resuming
sessions. While in a Claude Code session, just type:

```
>resume
```

(Also works: `>continue`, `>handoff`)

This will:

1. Copy the current session ID to your clipboard
2. Show instructions to terminate Claude Code and run `aichat resume <paste>`
3. Block the prompt (Claude won't process it, so no more tokens spent)

This is a quick escape hatch when you want to continue the work in a fresh 
session using any of the methods provided by `aichat` (trim, smart-trim, rollover)
while Claude Code is still running — no need to manually find the session ID.

<a id="tmux-cli-terminal-automation"></a>
# 🎮 tmux-cli — Terminal Automation

> **Note**: While the description below focuses on Claude Code, tmux-cli works with any CLI coding agent.

![tmux-cli demo](demos/tmux-cli-demo-short.gif)

**Think Playwright for terminals** - Terminal automation for AI agents.

tmux-cli enables Claude Code to programmatically control terminal applications:
test interactive scripts, debug with pdb, launch and interact with other CLI agents.

**Important**: You don't need to learn tmux-cli commands. Claude Code handles
everything automatically—just describe what you want.

**Works anywhere**: Automatically handles both local tmux panes and remote sessions.

<a id="tmux-cli-deep-dive"></a>
## 🎮 tmux-cli Deep Dive

### What Claude Code Can Do With tmux-cli

1. **Test Interactive Scripts** - CC can run and interact with scripts that 
   require user input, answering prompts automatically based on your instructions.

2. **UI Development & Testing** - CC can launch web servers and coordinate with 
   browser automation tools to test your applications.

3. **Interactive Debugging** - CC can use debuggers (pdb, node inspect, gdb) to 
   step through code, examine variables, and help you understand program flow.

4. **Claude-to-Claude Communication** - CC can launch another Claude Code instance 
   to get specialized help or code reviews.

Claude Code knows how to use tmux-cli through its built-in help. You just describe 
what you want, and CC handles the technical details.

For complete command reference, see [docs/tmux-cli-instructions.md](docs/tmux-cli-instructions.md).

### Setting up tmux-cli for Claude Code

To enable CC to use tmux-cli, add this snippet to your global
`~/.claude/CLAUDE.md` file:

```markdown
# tmux-cli Command to interact with CLI applications

`tmux-cli` is a bash command that enables Claude Code to control CLI applications 
running in separate tmux panes - launch programs, send input, capture output, 
and manage interactive sessions. Run `tmux-cli --help` for detailed usage 
instructions.

Example uses:
- Interact with a script that waits for user input
- Launch another Claude Code instance to have it perform some analysis or review or 
  debugging etc
- Run a Python script with the Pdb debugger to step thru its execution, for 
  code-understanding and debugging
- Launch web apps and test them with browser automation MCP tools like Playwright or 
Chrome Dev Tools.
```

More frequently, I use this method: I launch another CLI-agent (say Codex-CLI) 
in another tmux pane, and say something like this to the first agent:

> There's another coding agent "Codex" running in tmux Pane 3. Feel free to use Codex 
to help you with your task or review your work. You can communicate with Codex using
the tmux-cli command; you can do tmux-cli --help to see how to use it.

## Tmux-cli skill

To make it easier to have Claude-Code use this command, there's a **tmux-cli plugin** in this repo; once you install it, you can simply say "use your tmux-cli skill to get help from Codex running in tmux pane 3".

For detailed instructions, see [docs/tmux-cli-instructions.md](docs/tmux-cli-instructions.md).

All of this assumes you're familiar and comfortable with tmux, and (like me) run
all CLI coding sessions inside tmux sessions.


<a id="lmsh-experimental"></a>
# 🚀 lmsh (Experimental)

Natural language shell - type what you want in plain English, get an editable command.

```bash
# Direct usage - translate, edit, execute, then enter interactive mode
$ lmsh "show me all python files modified today"
find . -name "*.py" -mtime 0  # <-- Edit before running

# Or interactive mode
$ lmsh
lmsh> show recent docker containers
docker ps -n 5  # <-- Edit before running
```

**Features:**
- Rust-based for instant startup (<1ms binary load time)
- Translates natural language to shell commands using Claude Code CLI
- Commands are editable before execution - full control
- Preserves your shell environment

**Note:** Requires Claude Code CLI (`claude` command) to be installed. The translation adds ~2-3s due to Claude Code CLI startup.

**Installation:**
```bash
# Install from crates.io (easiest, requires Rust)
cargo install lmsh

# Or build from source
cd lmsh && cargo build --release
cp target/release/lmsh ~/.cargo/bin/
# Or: make lmsh-install
```

See [docs/lmsh.md](docs/lmsh.md) for details.

<a id="status-line"></a>
## 📊 Status Line

A custom status line script for Claude Code is available at
[`scripts/statusline.sh`](scripts/statusline.sh). It displays model name,
project directory, git branch, git status indicators, and a context window
progress bar that changes color as you approach the limit.

To use it, copy the script and configure Claude Code:

```bash
cp scripts/statusline.sh ~/.claude/
chmod +x ~/.claude/statusline.sh
```

Add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/statusline.sh"
  }
}
```

Requires `jq` and a Nerd Font for powerline symbols.

<a id="utilities"></a>
# 🔐 Utilities

<a id="vault"></a>
## 🔐 vault

Centralized encrypted backup for .env files across all your projects using SOPS.

```bash
vault sync      # Smart sync (auto-detect direction)
vault encrypt   # Backup .env to ~/Git/dotenvs/
vault decrypt   # Restore .env from centralized vault
vault list      # Show all project backups
vault status    # Check sync status for current project
```

### Key Features

- Stores all encrypted .env files in `~/Git/dotenvs/`
- Automatic sync direction detection
- GPG encryption via SOPS
- Timestamped backups for safety

For detailed documentation, see [docs/vault-documentation.md](docs/vault-documentation.md).

<a id="env-safe"></a>
## 🔍 env-safe

Safely inspect .env files without exposing sensitive values. Designed for Claude Code and other automated tools that need to work with environment files without accidentally leaking secrets.

```bash
env-safe list                    # List all environment variable keys
env-safe list --status           # Show keys with defined/empty status  
env-safe check API_KEY           # Check if a specific key exists
env-safe count                   # Count total, defined, and empty variables
env-safe validate                # Validate .env file syntax
env-safe --help                  # See all options
```

### Key Features

- **No Value Exposure** - Never displays actual environment values
- **Safe Inspection** - Check which keys exist without security risks
- **Syntax Validation** - Verify .env file format is correct
- **Status Checking** - See which variables are defined vs empty
- **Claude Code Integration** - Works with protection hooks to provide safe alternative

### Why env-safe?

Claude Code is completely blocked from directly accessing .env files - no reading, writing, or editing allowed. This prevents both accidental exposure of API keys and unintended modifications. The `env-safe` command provides the only approved way for Claude Code to inspect environment configuration safely, while any modifications must be done manually outside of Claude Code.

<a id="claude-code-safety-hooks"></a>
## 🛡️ Claude Code Safety Hooks

This repository includes a comprehensive set of safety hooks that enhance Claude
Code's behavior and prevent dangerous operations.

### Key Safety Features

- **File Deletion Protection** - Blocks `rm` commands, enforces TRASH directory
  pattern
- **Git Commit Protection** - Requires user approval before any git commit
  (uses Claude Code's permission prompt UI)
- **Git Add Protection** - Smart staging control:
  - Hard blocks: `git add .`, `git add ../`, `git add *`, `git add -A/--all`
  - New files: Allowed without permission
  - Modified files: Requires user approval (permission prompt)
  - Directories: Uses dry-run to detect files, asks permission if modified files
- **Environment Security** - Blocks all .env file operations (read/write/edit),
  suggests `env-safe` command for safe inspection
- **Context Management** - Blocks reading files >500 lines to prevent context
  bloat
- **Command Enhancement** - Enforces ripgrep (`rg`) over grep for better
  performance

### Quick Setup

1. Copy the hooks configuration from `hooks/settings.sample.json` 

2. Add the hooks to your global Claude settings at `~/.claude/settings.json`:
   - If the file doesn't exist, create it
   - Copy the "hooks" section from settings.sample.json
   - Replace `/path/to/claude-code-tools` with your actual path to this repository
   
   Example ~/.claude/settings.json:
   ```json
   {
     "hooks": {
       // ... hooks configuration from settings.sample.json ...
     }
   }
   ```

### Available Hooks

- `bash_hook.py` - Main hook that orchestrates all bash command checks
- `git_commit_block_hook.py` - User permission prompt for git commits
- `git_add_block_hook.py` - Smart staging: blocks dangerous patterns, prompts
  for modified files
- `env_file_protection_hook.py` - Blocks all .env file operations
- `file_size_conditional_hook.py` - Prevents reading huge files
- `grep_block_hook.py` - Enforces ripgrep usage
- `notification_hook.sh` - Sends ntfy.sh notifications

For complete documentation, see [hooks/README.md](hooks/README.md).

<a id="using-claude-code-with-open-weight-anthropic-api-compatible-llm-providers"></a>
## 🤖 Using Claude Code with Open-weight Anthropic API-compatible LLM Providers

You can use Claude Code with alternative LLMs served via Anthropic-compatible
APIs, e.g. Kimi-k2, GLM4.5 (from zai), Deepseek-v3.1. 
Add these functions to your shell config (.bashrc/.zshrc):

```bash
kimi() {
    (
        export ANTHROPIC_BASE_URL=https://api.moonshot.ai/anthropic
        export ANTHROPIC_AUTH_TOKEN=$KIMI_API_KEY
        claude "$@"
    )
}

zai() {
    (
        export ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic
        export ANTHROPIC_AUTH_TOKEN=$Z_API_KEY
        claude "$@"
    )
}

dseek() {
    (
        export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
        export ANTHROPIC_AUTH_TOKEN=${DEEPSEEK_API_KEY}
        export ANTHROPIC_MODEL=deepseek-chat
        export ANTHROPIC_SMALL_FAST_MODEL=deepseek-chat        
        claude "$@"
    )
}
```

After adding these functions:
- Set your API keys: `export KIMI_API_KEY=your-kimi-key`,
  `export Z_API_KEY=your-z-key`, `export DEEPSEEK_API_KEY=your-deepseek-key`
- Run `kimi` to use Claude Code with the Kimi K2 LLM
- Run `zai` to use Claude Code with the GLM-4.5 model
- Run `dseek` to use Claude Code with the DeepSeek model

The functions use subshells to ensure the environment variables don't affect
your main shell session, so you could be running multiple instances of Claude Code,
each using a different LLM.

### Using Claude Code and Codex with Local LLMs

You can run **Claude Code** and **OpenAI Codex CLI** with local models using
[llama.cpp](https://github.com/ggml-org/llama.cpp)'s server for fully offline usage.

- **Claude Code** uses the Anthropic-compatible `/v1/messages` endpoint with models
  like GPT-OSS-20B, Qwen3-Coder-30B, Qwen3-Next-80B, and Nemotron-3-Nano
- **Codex CLI** uses the OpenAI-compatible `/v1/chat/completions` endpoint with GPT-OSS

For complete setup instructions including llama-server commands, config files, and
command-line options for switching models, see
**[docs/local-llm-setup.md](docs/local-llm-setup.md)**.

<a id="documentation"></a>
## 📚 Documentation

- [tmux-cli detailed instructions](docs/tmux-cli-instructions.md) - 
  Comprehensive guide for using tmux-cli
- [Claude Code tmux tutorials](docs/claude-code-tmux-tutorials.md) - 
  Additional tutorials and examples
- [Vault documentation](docs/vault-documentation.md) - 
  Complete guide for the .env backup system
- [Hook configuration](hooks/README.md) - Setting up Claude Code hooks

<a id="requirements"></a>
## 📋 Requirements

- Python 3.11+
- uv (for installation)
- **Node.js 16+** (for interactive UI - typically already installed with Claude Code)
- tmux (for tmux-cli functionality)
- SOPS (for vault functionality)

<a id="development"></a>
## 🛠️ Development

### Architecture

The `aichat` command has three layers:

- **Python** (`claude_code_tools/`) - CLI entry points, backend logic, session parsing
- **Rust** (`rust-search-ui/`) - Search TUI with Tantivy full-text search
- **Node.js** (`node_ui/`) - Action menus (resume, export, trim, etc.)

Flow: Python CLI (`aichat search`) invokes Rust binary → Rust TUI for search →
user selects session → hands off to Node.js menus → menus call Python backend.

### Prerequisites

- **UV** - `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Rust/Cargo** - `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`
- **Node.js 16+** - Required for action menus

### Setup

```bash
git clone https://github.com/pchalasani/claude-code-tools
cd claude-code-tools
uv venv --python 3.11
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv sync
cd node_ui && npm install && cd ..
make install                  # Python (editable mode)
make aichat-search-install    # Rust binary
```

### Testing Changes

- **Python**: No action needed (editable mode - changes apply immediately)
- **Node.js**: No action needed (runs directly from `node_ui/`)
- **Rust**: Run `make aichat-search-install` to rebuild and install

### Publishing (Python Package)

For releasing to PyPI:

```bash
make all-patch   # Bump patch, push, GitHub release, build
make all-minor   # Bump minor, push, GitHub release, build
make all-major   # Bump major, push, GitHub release, build
uv publish       # Publish to PyPI (after any of the above)
```

These commands automatically:

1. Run `make prep-node` to ensure `node_ui/node_modules/` is up-to-date
2. Bump version → push to GitHub → create GitHub release
3. Build package (includes `node_modules/` so users don't need `npm install`)

Then run `uv publish` to upload to PyPI.

**Note:** Users need Node.js 16+ installed to run `aichat` action menus, but
they do NOT need npm — the package includes pre-installed dependencies.

### Publishing (Rust Binaries)

```bash
make aichat-search-publish  # Bump version and publish to crates.io
make lmsh-publish           # Bump version and publish to crates.io
```

### Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Test thoroughly
5. Commit your changes
6. Push to your fork
7. Open a Pull Request

### Available Make Commands

Run `make help` for full list. Key commands:

| Command | Description |
|---------|-------------|
| `make install` | Install Python in editable mode |
| `make aichat-search-install` | Build and install Rust binary |
| `make prep-node` | Install node_modules (auto-runs before publish) |
| `make all-patch/minor/major` | Bump + push + build (for PyPI) |
| `make aichat-search-publish` | Publish Rust binary to crates.io |

<a id="license"></a>
## 📄 License

MIT
