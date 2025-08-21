# lmshell

A fast, minimal natural language shell interface that translates conversational commands into editable shell commands.

## What it does

Type natural language → Get an editable shell command → Review/modify → Execute

Example:
```bash
$ lmshell
> show me all python files modified today
find . -name "*.py" -mtime 0  # <-- Editable command appears, press Enter to run
```

## Installation

Requires Rust toolchain:

```bash
cd lmshell/
cargo build --release
cp target/release/lmshell ~/.cargo/bin/
```

Or use the Makefile: `make lmshell-install`

Note: Ensure `~/.cargo/bin` is in your PATH.

## Usage

```bash
lmshell                           # Interactive mode
lmshell "show me python files"    # Translate, edit, execute, then interactive mode
lmshell --version                # Version info
```

## Features

- **Editable commands** - Review and modify before execution
- **Fast startup** - Optimized Rust binary (~1ms)
- **Claude-powered** - Uses Claude for natural language understanding
- **Shell preservation** - Maintains your shell environment and aliases

## Note

Claude's API startup adds ~2-3s latency. Future versions may explore faster local models for instant response.