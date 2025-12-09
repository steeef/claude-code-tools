# steeef-safety Plugin

Additional safety hooks for Claude Code that complement the upstream `safety-hooks` plugin.

## Features

### kubectl Safety Hook

Protects against accidental Kubernetes infrastructure changes:

- **Allows** read-only commands: `get`, `describe`, `logs`, `top`, `version`, `cluster-info`, `config`, `explain`, `api-resources`, `api-versions`, `diff`
- **Blocks** destructive commands: `delete`, `apply`, `create`, `replace`, `patch`, `edit`, `scale`, `rollout`, `annotate`, `label`, `expose`, `run`, `exec`, `cp`
- **Asks permission** for: `port-forward`, `proxy`
- Allows `--dry-run` flag to bypass blocking

### Terraform Safety Hook

Protects against accidental infrastructure changes:

- **Allows** read-only commands: `plan`, `show`, `validate`, `version`, `providers`, `output`, `state`, `graph`, `console`, `fmt`, `get`, `init`, `workspace`
- **Blocks** destructive commands: `apply`, `destroy`, `import`, `taint`, `untaint`, `refresh`

### Skill Activation Hook

Auto-suggests relevant skills based on prompt content:

- Analyzes user prompts for keywords and patterns
- Suggests skills like `codex`, `github-actions`, `loki-debug`, `tatari-turbolift`
- Implements cooldown to avoid spamming suggestions
- Configuration in `skill-rules.json`

### CLAUDE.md Protection Hook

Enforces best practices for AI coding agent instructions:

- **Blocks** direct writes to `CLAUDE.md`
- **Suggests** writing to `AGENTS.md` and creating a symlink
- Ensures version control friendly approach

## Installation

This plugin is included in the `steeef/claude-code-tools` fork. When installed as a Claude Code plugin, the hooks are automatically registered.

## Usage

The hooks run automatically when the plugin is activated. No configuration needed beyond plugin installation.

### Customizing Skill Activation

Edit `hooks/skill-rules.json` to:
- Add new skills with keywords and patterns
- Adjust scoring weights
- Configure cooldown periods
