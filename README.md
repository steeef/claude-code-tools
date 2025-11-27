# claude-code-tools

A collection of practical tools, hooks, and utilities for enhancing Claude Code
and other CLI coding agents.

## ⚠️ Breaking Change Notice (v0.3.0)

**All session management commands are now consolidated under the `aichat` command group.**

Flat commands (`claude-continue`, `find-claude-session`, etc.) have been **removed**.
All functionality is now accessed via `aichat` subcommands:

| Old Command | New Command |
|-------------|-------------|
| `claude-continue <session>` | `aichat resume <session>` |
| `codex-continue <session>` | `aichat resume <session>` |
| `find-claude-session <keywords>` | `aichat find-claude <keywords>` |
| `find-codex-session <keywords>` | `aichat find-codex <keywords>` |
| `find-session <keywords>` | `aichat find <keywords>` |
| `export-claude-session <session>` | `aichat export <session>` |
| `export-codex-session <session>` | `aichat export <session>` |
| `session-menu <session>` | `aichat menu <session>` |
| `trim-session <session>` | `aichat trim <session>` |
| `smart-trim <session>` | `aichat smart-trim <session>` |
| `find-original-session <session>` | `aichat find-original <session>` |
| `find-derived-sessions <session>` | `aichat find-derived <session>` |
| `delete-session <session>` | `aichat delete <session>` |

**Key improvements:**
- `aichat resume` and `aichat export` now **auto-detect session type** (Claude or Codex)
- Support for **cross-agent continuation** (continue a Claude session with Codex, or vice versa)
- Cleaner, more intuitive command structure

## Table of Contents

- [🚀 Quick Start](#quick-start)
- [🎮 tmux-cli — Terminal Automation](#tmux-cli-terminal-automation)
- [💬 aichat — Session Management](#aichat-session-management)
- [🚀 lmsh (Experimental) — natural language shell](#lmsh-experimental)
- [🔐 Utilities](#utilities)
- [🛡️ Claude Code Safety Hooks](#claude-code-safety-hooks)
- [🤖 Using with Alternative LLM Providers](#using-claude-code-with-open-weight-anthropic-api-compatible-llm-providers)
- [📚 Documentation](#documentation)
- [📋 Requirements](#requirements)
- [🛠️ Development](#development)
- [📄 License](#license)

<a id="tmux-cli-terminal-automation"></a>
# 🎮 tmux-cli — Terminal Automation

<a id="tmux-cli-bridging-claude-code-and-interactive-clis"></a>
## Overview: Bridging Claude Code and Interactive CLIs

> **Note**: While the description below focuses on Claude Code, tmux-cli works with any CLI coding agent.

 ![tmux-cli demo](demos/tmux-cli-demo-short.gif)

Consider these scenarios:

You're using Claude Code (CC) to build an interactive script. The script prompts 
for user input, but CC can't respond to prompts.

You want Claude Code to debug using pdb, stepping through code line by line.

You need your CLI code agent to launch another instance of the same OR different 
CLI code agent, AND interact with it, not as a hidden sub-agent, 
but as a visible session you can monitor (as shown in gif above).

**tmux-cli enables these workflows** by giving Claude Code programmatic control 
over terminal applications.

For those new to [tmux](https://github.com/tmux/tmux/wiki), it's a terminal 
multiplexer that lets you create and manage multiple terminal sessions. The key 
benefit for our purposes is that tmux is scriptable and allows sending keystrokes 
to specific panes or sessions programmatically.

**Important**: You don't need to learn tmux-cli commands. Claude Code will handle 
all the interactions automatically. Just tell CC what you want to do, and it will 
use tmux-cli behind the scenes.

**Think Playwright for terminals** - Terminal automation for AI agents.

**Works anywhere**: Automatically handles both local tmux panes and remote sessions.

<a id="quick-start"></a>
## 🚀 Quick Start

```bash
# Install from PyPI (recommended)
uv tool install claude-code-tools

# Or install the latest development version from GitHub
uv tool install git+https://github.com/pchalasani/claude-code-tools
```

### What You Get

All tools are accessed through the **unified `aichat` command** and standalone utilities.

**🎯 Quick Examples:**

```bash
aichat                        # Action menu for latest session(s)
aichat abc123                 # Action menu for specific session
aichat find "keywords"        # Find sessions across all agents
aichat export abc123          # Export session to text
aichat trim abc123            # Compress session
aichat --help                 # See all subcommands
```

**Available Tools:**

Session Management (`aichat`):
- Unified command for all session operations (find, resume, export, trim, query)
- Works with both Claude Code and Codex sessions
- Omit session ID to use latest session(s) for current project/branch
- See [aichat documentation](#aichat-session-management) for details

Other Utilities (standalone commands):
- `tmux-cli` - Interactive CLI controller ("Playwright for terminals")
- `vault` - Encrypted .env backup and sync
- `env-safe` - Safe .env inspection without exposing values

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
the tmux-cli command; you can do tmu-cli --help to see how to use it.


For detailed instructions, see [docs/tmux-cli-instructions.md](docs/tmux-cli-instructions.md).

All of this assumes you're familiar and comfortable with tmux, and (like me) run
all CLI coding sessions inside tmux sessions.

<a id="aichat-session-management"></a>
# 💬 aichat — Session Management

The `aichat` command is your unified interface for managing Claude Code and Codex
sessions. It provides search, resume, export, trim, query, and navigation tools
through an interactive Node.js-based UI.

**Key principle:** Wherever a session ID is expected, you can omit it—the command
will find the latest Claude and Codex sessions for the current project/branch and
let you choose.

```bash
aichat --help              # See all subcommands
aichat <subcommand> --help # Help for specific subcommand
```

**Session ID formats** (accepted by most commands):

- Full file path: `~/.claude/projects/.../abc123.jsonl`
- Full session ID: `abc123-def456-789-...`
- Partial session ID: `abc123` (if unique match)

---

## aichat find — Search Sessions

Search and select from Claude Code and Codex sessions. The interactive UI guides
you through filtering options, so you don't need to memorize CLI flags.

```bash
aichat find                    # All sessions in current project (shows UI)
aichat find "keywords"         # Search by keywords
aichat find -g                 # Global search (all projects)
```

**Variants:**

- `aichat find-claude` — Claude sessions only
- `aichat find-codex` — Codex sessions only

**Common CLI options** (or just run `aichat find` and use the UI):

| Option | Description |
|--------|-------------|
| `-g, --global` | Search all projects |
| `-n N` | Limit to N results |
| `--original` | Exclude trimmed/continued sessions |
| `--agents claude` | Filter by agent |
| `--before`, `--after` | Time filters (YYYYMMDD or MM/DD/YY) |

After selecting a session, you'll see the **action menu** with options to show
path, copy, export, query, or access resume options.

![find-claude-session.png](demos/find-claude-session.png)

---

## aichat resume — Resume & Manage Sessions

Access a session and choose how to resume or manage it.

```bash
aichat resume                  # Latest session(s) for current project
aichat resume <session-id>     # Specific session
aichat                         # Same as: aichat resume (no args)
aichat <session-id>            # Same as: aichat resume <session-id>
```

**Variants:** `aichat resume-claude`, `aichat resume-codex`

**Action menu options:**

- **Show path** — Display session file location
- **Copy** — Copy session file to another location
- **Export** — Export to readable text file (.txt)
- **Query** — Ask any question about the session (uses agent in non-interactive mode with parallel sub-agents)

**Resume submenu options:**

- **Resume as-is** — Continue the session directly
- **Clone and resume** — Create a copy and resume the copy
- **Trim + resume** — Compress large tool results, then resume
- **Smart trim + resume** — AI-powered trimming (EXPERIMENTAL)
- **Continue with context** — Transfer context to a fresh session using sub-agents (useful when running out of context)

---

## Direct Actions

Several actions from the menus above are also available as direct commands,
skipping the multi-stage menus:

| Command | Description |
|---------|-------------|
| `aichat export [session]` | Export session to text |
| `aichat trim [session]` | Trim large tool results |
| `aichat smart-trim [session]` | AI-powered trimming (EXPERIMENTAL) |
| `aichat delete [session]` | Delete with confirmation |
| `aichat find-original [session]` | Trace back to original session |
| `aichat find-derived [session]` | Find all derived sessions |

All commands accept session ID or file path. If omitted, shows latest sessions
for selection.

Run `aichat <command> --help` for detailed options

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
- **Git Safety** - Advanced git add protection with:
  - Hard blocks: `git add .`, `git add ../`, `git add *`, `git add -A/--all`
  - Speed bumps: Shows files before staging directories (e.g., `git add src/`)
  - Commit speed bump: Warns on first attempt, allows on second
  - Prevents unsafe checkouts and accidental data loss
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

- `bash_hook.py` - Comprehensive bash command safety checks
- `env_file_protection_hook.py` - Blocks all .env file operations
- `file_size_conditional_hook.py` - Prevents reading huge files
- `grep_block_hook.py` - Enforces ripgrep usage
- `notification_hook.sh` - Sends ntfy.sh notifications
- `pretask/posttask_subtask_flag.py` - Manages sub-agent state

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

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/username/claude-code-tools
   cd claude-code-tools
   ```

2. Create and activate a virtual environment with uv:
   ```bash
   uv venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install in development mode:
   ```bash
   make install      # Install tools in editable mode
   make dev-install  # Install with dev dependencies (includes commitizen)
   ```

### Making Changes

- The tools are installed in editable mode, so changes take effect immediately
- Test your changes by running the commands directly
- Follow the existing code style and conventions

### Version Management

The project uses commitizen for version management:

```bash
make patch  # Bump patch version (0.0.X)
make minor  # Bump minor version (0.X.0)  
make major  # Bump major version (X.0.0)
```

### Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Test thoroughly
5. Commit your changes (commitizen will format the commit message)
6. Push to your fork
7. Open a Pull Request

### Available Make Commands

Run `make help` to see all available commands:
- `make install` - Install in editable mode for development
- `make dev-install` - Install with development dependencies
- `make release` - Bump patch version and install globally
- `make patch/minor/major` - Version bump commands

<a id="license"></a>
## 📄 License

MIT
