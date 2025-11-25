#!/usr/bin/env python3
"""
aichat - Unified CLI for AI chat session management tools.

This provides a grouped command interface for managing Claude Code and
Codex sessions, following the pattern of tools like git, docker, etc.

All session-related tools are accessible as subcommands:
    aichat find            - Find sessions across all agents
    aichat find-claude     - Find Claude sessions
    aichat find-codex      - Find Codex sessions
    aichat menu            - Interactive session menu
    aichat trim            - Trim session content
    ... and more

For backward compatibility, all flat commands (find-claude-session,
etc.) are still available.
"""

import click


class SessionIDGroup(click.Group):
    """Custom group that treats unknown commands as session IDs for menu."""

    def parse_args(self, ctx, args):
        # If the first arg looks like a session ID (not a known command), route to menu
        if args and args[0] not in self.commands and not args[0].startswith('-'):
            # Treat as session ID - prepend 'menu' to make it a menu command
            args = ['menu'] + args
        return super().parse_args(ctx, args)


@click.group(cls=SessionIDGroup)
@click.version_option()
def main():
    """
    Session management tools for Claude Code and Codex.

    This is the recommended interface for managing AI chat sessions.
    Each subcommand provides specialized functionality for finding,
    managing, and manipulating session files.

    For help on any subcommand, use:

    \b
        aichat COMMAND --help

    Examples:

    \b
        aichat abc123-def456          # Shortcut for: aichat menu abc123-def456
        aichat find "langroid"
        aichat find-claude "bug fix"
        aichat menu abc123-def456
        aichat trim session-id.jsonl
    """
    pass


@main.command("find", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.pass_context
def find(ctx):
    """Find sessions across all agents (Claude Code, Codex, etc.)."""
    import sys
    # Replace 'find' with 'find-session' in argv for the actual command
    sys.argv = [sys.argv[0].replace('aichat', 'find-session')] + ctx.args
    from claude_code_tools.find_session import main as find_main
    find_main()


@main.command("find-claude", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.pass_context
def find_claude(ctx):
    """Find Claude Code sessions by keywords."""
    import sys
    sys.argv = [sys.argv[0].replace('aichat', 'find-claude-session')] + ctx.args
    from claude_code_tools.find_claude_session import main as find_claude_main
    find_claude_main()


@main.command("find-codex", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.pass_context
def find_codex(ctx):
    """Find Codex sessions by keywords."""
    import sys
    sys.argv = [sys.argv[0].replace('aichat', 'find-codex-session')] + ctx.args
    from claude_code_tools.find_codex_session import main as find_codex_main
    find_codex_main()


@main.command("find-original", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.pass_context
def find_original(ctx):
    """Find the original session from a trimmed/continued session."""
    import sys
    sys.argv = [sys.argv[0].replace('aichat', 'find-original-session')] + ctx.args
    from claude_code_tools.find_original_session import (
        main as find_original_main,
    )
    find_original_main()


@main.command("find-derived", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.pass_context
def find_derived(ctx):
    """Find derived sessions (trimmed/continued) from an original."""
    import sys
    sys.argv = [sys.argv[0].replace('aichat', 'find-trimmed-sessions')] + ctx.args
    from claude_code_tools.find_trimmed_sessions import (
        main as find_derived_main,
    )
    find_derived_main()


@main.command("menu", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.pass_context
def menu(ctx):
    """Interactive menu for a specific session (by ID or path)."""
    import sys
    sys.argv = [sys.argv[0].replace('aichat', 'session-menu')] + ctx.args
    from claude_code_tools.session_menu_cli import main as menu_main
    menu_main()


@main.command("trim")
@click.argument("session", required=True)
@click.option("--simple-ui", is_flag=True, help="Use simple CLI trim instead of Node UI")
def trim(session, simple_ui):
    """Trim/resume session - shows menu of trim options.

    Opens Node UI with trim/resume options (resume, clone, trim+resume,
    smart-trim, continue). Use --simple-ui for direct CLI trim.
    """
    import sys
    from pathlib import Path
    from claude_code_tools.session_utils import detect_agent_from_path, find_session_file
    from claude_code_tools.node_menu_ui import run_node_menu_ui
    from claude_code_tools.session_menu_cli import execute_action

    if simple_ui:
        # Fall back to old trim-session CLI
        sys.argv = [sys.argv[0].replace('aichat', 'trim-session'), session]
        from claude_code_tools.trim_session import main as trim_main
        trim_main()
        return

    # Resolve session
    detected_agent = None
    session_file = None
    project_path = None

    input_path = Path(session).expanduser()
    if input_path.exists() and input_path.is_file():
        session_file = input_path
        detected_agent = detect_agent_from_path(session_file)
    else:
        result = find_session_file(session)
        if result:
            detected_agent, session_file, project_path, _ = result

    if not session_file:
        print(f"Error: Could not find session: {session}", file=sys.stderr)
        sys.exit(1)

    agent = detected_agent or "claude"
    session_id = session_file.stem

    # Build session dict for Node UI
    line_count = 0
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            line_count = sum(1 for _ in f)
    except Exception:
        pass

    # Extract project info if not already set
    if not project_path:
        if agent == "claude":
            from claude_code_tools.session_utils import extract_cwd_from_session
            project_path = extract_cwd_from_session(session_file) or str(Path.cwd())
        else:
            project_path = str(Path.cwd())

    session_dict = {
        "agent": agent,
        "agent_display": agent.title(),
        "session_id": session_id,
        "mod_time": session_file.stat().st_mtime,
        "create_time": session_file.stat().st_ctime,
        "lines": line_count,
        "project": Path(project_path).name,
        "preview": "",
        "cwd": project_path,
        "branch": "",
        "file_path": str(session_file),
        "is_trimmed": False,
        "derivation_type": None,
        "is_sidechain": False,
    }

    def handler(sess, action, kwargs=None):
        execute_action(
            action, agent, session_file, project_path,
            action_kwargs=kwargs,
        )

    rpc_path = str(Path(__file__).parent / "action_rpc.py")
    run_node_menu_ui(
        [session_dict], [session_id], handler,
        start_screen="trim_menu",
        rpc_path=rpc_path,
    )


@main.command("smart-trim", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.pass_context
def smart_trim(ctx):
    """Smart trim using Claude SDK agents (EXPERIMENTAL)."""
    import sys
    sys.argv = [sys.argv[0].replace('aichat', 'smart-trim')] + ctx.args
    from claude_code_tools.smart_trim import main as smart_trim_main
    smart_trim_main()


@main.command("export", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.option("--agent", type=click.Choice(["claude", "codex"], case_sensitive=False), help="Force export with specific agent")
@click.argument("session", required=True)
@click.pass_context
def export_session(ctx, agent, session):
    """Export session to text/markdown format.

    Auto-detects session type and uses matching export command.
    Use --agent to override and force export with a specific agent.
    """
    import sys
    from pathlib import Path
    from claude_code_tools.session_utils import detect_agent_from_path, find_session_file

    # Try to detect session type
    detected_agent = None
    session_file = None

    # First check if it's a file path
    input_path = Path(session).expanduser()
    if input_path.exists() and input_path.is_file():
        session_file = input_path
        detected_agent = detect_agent_from_path(session_file)
    else:
        # Try to find by session ID
        result = find_session_file(session)
        if result:
            detected_agent, session_file, _, _ = result

    # Determine which agent to use
    if agent:
        # User explicitly specified agent
        export_agent = agent.lower()
        if detected_agent and detected_agent != export_agent:
            print(f"\nℹ️  Detected {detected_agent.upper()} session")
            print(f"ℹ️  Exporting with {export_agent.upper()} (user specified)")
        else:
            print(f"\nℹ️  Exporting with {export_agent.upper()} (user specified)")
    elif detected_agent:
        # Use detected agent
        export_agent = detected_agent
        print(f"\nℹ️  Detected {detected_agent.upper()} session")
        print(f"ℹ️  Exporting with {export_agent.upper()}")
    else:
        # Default to Claude if cannot detect
        export_agent = "claude"
        print(f"\n⚠️  Could not detect session type, defaulting to CLAUDE")

    print()

    # Route to appropriate export command
    if export_agent == "claude":
        sys.argv = [sys.argv[0].replace('aichat', 'export-claude-session'), session] + ctx.args
        from claude_code_tools.export_claude_session import main as export_main
        export_main()
    else:
        sys.argv = [sys.argv[0].replace('aichat', 'export-codex-session'), session] + ctx.args
        from claude_code_tools.export_codex_session import main as export_main
        export_main()


@main.command("export-claude", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.pass_context
def export_claude(ctx):
    """Export Claude Code session to text/markdown format."""
    import sys
    sys.argv = [sys.argv[0].replace('aichat', 'export-claude-session')] + ctx.args
    from claude_code_tools.export_claude_session import (
        main as export_claude_main,
    )
    export_claude_main()


@main.command("export-codex", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.pass_context
def export_codex(ctx):
    """Export Codex session to text/markdown format."""
    import sys
    sys.argv = [sys.argv[0].replace('aichat', 'export-codex-session')] + ctx.args
    from claude_code_tools.export_codex_session import (
        main as export_codex_main,
    )
    export_codex_main()


@main.command("delete", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.pass_context
def delete(ctx):
    """Delete a session file with safety confirmation."""
    import sys
    sys.argv = [sys.argv[0].replace('aichat', 'delete-session')] + ctx.args
    from claude_code_tools.delete_session import main as delete_main
    delete_main()


@main.command("continue")
@click.option(
    "--agent",
    type=click.Choice(["claude", "codex"], case_sensitive=False),
    help="Skip agent choice prompt and use this agent",
)
@click.option(
    "--prompt",
    type=str,
    help="Skip custom prompt and use this for summarization instructions",
)
@click.argument("session", required=True)
def continue_session(agent, prompt, session):
    """Continue from an exported session (when running out of context).

    Shows lineage, then prompts for agent choice and custom instructions.
    Use --agent and/or --prompt to skip those prompts.
    """
    import sys
    from pathlib import Path
    from claude_code_tools.session_utils import (
        continue_with_options,
        detect_agent_from_path,
        find_session_file,
    )

    # Try to detect session type
    detected_agent = None
    session_file = None

    # First check if it's a file path
    input_path = Path(session).expanduser()
    if input_path.exists() and input_path.is_file():
        session_file = input_path
        detected_agent = detect_agent_from_path(session_file)
    else:
        # Try to find by session ID
        result = find_session_file(session)
        if result:
            detected_agent, session_file, _, _ = result

    if not session_file:
        print(f"❌ Could not find session: {session}", file=sys.stderr)
        sys.exit(1)

    # Use detected agent as the "current" agent for the session
    current_agent = detected_agent or "claude"

    # Call unified continue flow
    # - preset_agent: if user specified --agent, skip agent prompt
    # - preset_prompt: if user specified --prompt, skip custom prompt
    continue_with_options(
        session_file_path=str(session_file),
        current_agent=current_agent,
        preset_agent=agent,
        preset_prompt=prompt if prompt is not None else None,
    )


if __name__ == "__main__":
    main()
