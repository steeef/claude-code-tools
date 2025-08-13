# claude-code-tools

A collection of practical tools, hooks, and utilities for enhancing Claude Code
and other CLI coding agents.

## 🎮 tmux-cli: Bridging Claude Code and Interactive CLIs

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

## 🚀 Quick Start

```bash
# Install from PyPI (recommended)
uv tool install claude-code-tools

# Or install the latest development version from GitHub
uv tool install git+https://github.com/pchalasani/claude-code-tools
```

This gives you:
- `tmux-cli` - The interactive CLI controller we just covered
- `find-claude-session` - Search and resume Claude Code sessions by keywords
- `vault` - Encrypted backup for your .env files

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
- Launch web apps and test them with browser automation MCP tools like Puppeteer
```

Incidentally, installing the Puppeteer MCP tool is easy:

```bash
claude mcp add puppeteer -- npx -y @modelcontextprotocol/server-puppeteer
```

For detailed instructions, see [docs/tmux-cli-instructions.md](docs/tmux-cli-instructions.md).

## 🔍 find-claude-session

Search and resume Claude Code sessions by keywords with an interactive UI.

### Setup (Recommended)

Add this function to your shell config (.bashrc/.zshrc) for persistent directory
changes:

```bash
fcs() {
    # Check if user is asking for help
    if [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
        find-claude-session --help
        return
    fi
    # Run find-claude-session in shell mode and evaluate the output
    eval "$(find-claude-session --shell "$@" | sed '/^$/d')"
}
```

Or source the provided function:
```bash
source /path/to/claude-code-tools/scripts/fcs-function.sh
```

### Usage

```bash
# Search in current project
fcs "keyword1,keyword2,keyword3"

# Search across all Claude projects  
fcs "keywords" --global
fcs "keywords" -g
```

### Features

- Interactive session selection with previews
- Cross-project search capabilities
- Automatic session resumption with `claude -r`
- Persistent directory changes when resuming cross-project sessions

Note: You can also use `find-claude-session` directly, but directory changes
won't persist after exiting Claude Code.

For detailed documentation, see [docs/find-claude-session.md](docs/find-claude-session.md).

Looks like this -- 

![fcs.png](docs/fcs.png)

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

## 🛡️ Claude Code Safety Hooks

This repository includes a comprehensive set of safety hooks that enhance Claude
Code's behavior and prevent dangerous operations.

### Key Safety Features

- **File Deletion Protection** - Blocks `rm` commands, enforces TRASH directory
  pattern
- **Git Safety** - Prevents dangerous `git add -A`, unsafe checkouts, and
  accidental data loss  
- **Context Management** - Blocks reading files >500 lines to prevent context
  bloat
- **Command Enhancement** - Enforces ripgrep (`rg`) over grep for better
  performance

### Quick Setup

1. Copy the sample hooks configuration:
   ```bash
   cp hooks/settings.sample.json hooks/settings.json
   export CLAUDE_CODE_TOOLS_PATH=/path/to/claude-code-tools
   ```

2. Reference in your Claude Code settings or use `--hooks` flag:
   ```bash
   claude --hooks /path/to/hooks/settings.json
   ```

### Available Hooks

- `bash_hook.py` - Comprehensive bash command safety checks
- `file_size_conditional_hook.py` - Prevents reading huge files
- `grep_block_hook.py` - Enforces ripgrep usage
- `notification_hook.sh` - Sends ntfy.sh notifications
- `pretask/posttask_subtask_flag.py` - Manages sub-agent state

For complete documentation, see [hooks/README.md](hooks/README.md).

## 🤖 Using Claude Code with Open-weight Anthropic API-compatible LLM Providers

You can use Claude Code with alternative LLMs served via Anthropic-compatible
APIs. Add these functions to your shell config (.bashrc/.zshrc):

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
```

After adding these functions:
- Set your API keys: `export KIMI_API_KEY=your-kimi-key` and 
  `export Z_API_KEY=your-z-key`
- Run `kimi` to use Claude Code with the Kimi K2 LLM
- Run `zai` to use Claude Code with the GLM-4.5 model

The functions use subshells to ensure the environment variables don't affect 
your main shell session, so you could be running multiple instances of Claude Code,
each using a different LLM.

## 📚 Documentation

- [tmux-cli detailed instructions](docs/tmux-cli-instructions.md) - 
  Comprehensive guide for using tmux-cli
- [Claude Code tmux tutorials](docs/claude-code-tmux-tutorials.md) - 
  Additional tutorials and examples
- [Vault documentation](docs/vault-documentation.md) - 
  Complete guide for the .env backup system
- [Hook configuration](hooks/README.md) - Setting up Claude Code hooks

## 📋 Requirements

- Python 3.11+
- uv (for installation)
- tmux (for tmux-cli functionality)
- SOPS (for vault functionality)

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

## 📄 License

MIT
