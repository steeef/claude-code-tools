
Steps to install the `aichat-search` tool:

```bash
uv tool install claude-code-tools   # Python package
cargo install aichat-search         # Rust search TUI
```

Prerequisites:
  - Node.js 16+ — for action menus (resume, export, etc.)
  - Rust/Cargo — for aichat search

If user doesn't have uv or cargo:

```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh           # uv
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh  # Rust
```
