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
- **Claude-powered** - Uses Claude for natural language understanding
- **Shell preservation** - Maintains your shell environment and aliases

## Note

Claude's API startup adds ~2-3s latency. Future versions may explore faster local models for instant response.