# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is `claude-code-tools`, a collection of utilities for enhancing Claude Code and other CLI coding agents. The project provides three main tools:

- **tmux-cli**: Terminal automation that enables Claude Code to control interactive CLI applications
- **find-claude-session**: Search and resume Claude Code sessions by keywords with interactive UI
- **vault**: Centralized encrypted backup for .env files using SOPS

## Build System & Commands

The project uses `uv` as the package manager and `make` for common operations:

### Development Setup
```bash
make install          # Install in editable mode (for development)
make dev-install      # Install with dev dependencies (includes commitizen)
```

### Version Management
The project uses commitizen for semantic versioning:
```bash
make patch            # Bump patch version (0.0.X) and install
make minor            # Bump minor version (0.X.0) and install
make major            # Bump major version (X.0.0) and install
```

### Release Process
```bash
make release          # Alias for make patch
make all-patch        # Bump patch, push to GitHub, create release, and build for PyPI
make clean            # Clean build artifacts
```

## Architecture

### Package Structure
- `claude_code_tools/` - Main Python package containing all tool implementations
  - `find_claude_session.py` - Session search and resume functionality
  - `tmux_cli_controller.py` - Terminal automation via tmux
  - `dotenv_vault.py` - Encrypted .env backup system
  - `tmux_remote_controller.py` - Remote tmux session handling

### Entry Points
All tools are configured as console scripts in `pyproject.toml`:
- `find-claude-session` → `claude_code_tools.find_claude_session:main`
- `vault` → `claude_code_tools.dotenv_vault:main`
- `tmux-cli` → `claude_code_tools.tmux_cli_controller:main`

### Dependencies
- **click**: Command-line interface framework
- **fire**: Alternative CLI framework (used by some tools)
- **rich**: Terminal formatting and display

## Key Components

### tmux-cli Controller
Uses a **dual-mode architecture** that auto-detects tmux environment:
- **Local mode** (inside tmux): Operates on panes within current session via `TmuxCLIController`
- **Remote mode** (outside tmux): Creates separate sessions via `RemoteTmuxController`
- Provides unified API for launching interactive applications, sending keystrokes, capturing output, and session management
- Includes synchronization primitives (`wait_for_prompt`, `wait_for_idle`) for reliable CLI automation

### Session Finder
Interactive search through Claude Code session history with:
- Keyword-based filtering
- Cross-project search capabilities
- Automatic directory switching and session resumption
- Rich terminal UI with previews

### Vault System
SOPS-based encrypted backup for environment files:
- Centralized storage in `~/Git/dotenvs/`
- GPG encryption
- Smart sync direction detection
- Timestamped backups

## Safety Hooks Integration

The project includes comprehensive Claude Code safety hooks in the `hooks/` directory:

### Hook Types
- **bash_hook.py**: Prevents dangerous bash commands (rm, unsafe git operations)
- **file_size_conditional_hook.py**: Blocks reading large files to prevent context bloat
- **grep_block_hook.py**: Enforces ripgrep usage over grep
- **notification_hook.sh**: Sends ntfy.sh notifications for events

### Hook Configuration
Set `CLAUDE_CODE_TOOLS_PATH` environment variable and reference hooks in Claude Code settings:
```bash
export CLAUDE_CODE_TOOLS_PATH=/path/to/claude-code-tools
```

## Development Notes

- The project requires Python 3.11+
- Uses `uv` for dependency management and tool installation
- Version synchronization between `pyproject.toml` and `__init__.py`
- Hooks require the environment variable to resolve script paths
- Tools are designed to work both locally and in remote environments
