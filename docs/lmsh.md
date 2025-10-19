# lmsh

A fast, minimal natural language shell interface that translates conversational commands into editable shell commands.

## What it does

Type natural language → Get an editable shell command → Review/modify → Execute

Example:
```bash
$ lmsh
> show me all python files modified today
find . -name "*.py" -mtime 0  # <-- Editable command appears, press Enter to run
```

## Installation

```bash
# Install from crates.io (easiest, requires Rust)
cargo install lmsh

# Or build from source
cd lmsh/
cargo build --release
cp target/release/lmsh ~/.cargo/bin/
# Or: make lmsh-install
```

Note: Ensure `~/.cargo/bin` is in your PATH.

## Usage

```bash
lmsh                           # Interactive mode (uses Claude/Haiku by default)
lmsh "show me python files"    # Translate, edit, execute, then interactive mode
lmsh --agent claude            # Explicitly use Claude (default)
lmsh --agent codex             # Use Codex instead
lmsh --version                 # Version info
```

## Features

- **Editable commands** - Review and modify before execution
- **Fast startup** - Optimized Rust binary (~1ms)
- **Multiple AI agents** - Choose between Claude (default) or Codex for command translation
- **Shell preservation** - Maintains your shell environment and aliases
- **Clean output** - PTY-based execution with proper echo suppression (no garbled prompts or ANSI codes)

## Agent Selection

lmsh supports two AI agents for translating natural language to shell commands:

### Claude (default)
- **Model**: Haiku (fast and efficient)
- **Command**: `claude -p "<prompt>" --model haiku`
- **Requirement**: Claude Code CLI must be installed and configured
- **Best for**: General shell command translation with fast response times

### Codex
- **Model**: GPT-5 (advanced reasoning)
- **Command**: `codex exec "<prompt>"`
- **Requirement**: Codex CLI must be installed and configured
- **Best for**: Complex command construction requiring advanced reasoning

## Requirements

- At least one of the following CLI tools:
  - **Claude Code CLI** (`claude` command) - for default Claude agent
  - **Codex CLI** (`codex` command) - for Codex agent
- The translation step adds ~2-3s latency due to AI model inference time