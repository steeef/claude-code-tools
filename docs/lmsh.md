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
lmsh                           # Interactive mode
lmsh "show me python files"    # Translate, edit, execute, then interactive mode
lmsh --version                # Version info
```

## Features

- **Editable commands** - Review and modify before execution
- **Fast startup** - Optimized Rust binary (~1ms)
- **Claude-powered** - Leverages your existing Claude Code CLI by calling `claude -p <prompt>` in non-interactive mode
- **Shell preservation** - Maintains your shell environment and aliases

## Note

This tool requires the Claude Code CLI (`claude` command) to be installed and configured. The translation step adds ~2-3s latency due to Claude Code CLI startup time.