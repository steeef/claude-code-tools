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


@click.group(cls=SessionIDGroup, invoke_without_command=True)
@click.version_option()
@click.pass_context
def main(ctx):
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
        aichat                        # Action menu for latest session(s)
        aichat abc123-def456          # Shortcut for: aichat menu abc123-def456
        aichat find "langroid"
        aichat find-claude "bug fix"
        aichat menu abc123-def456
        aichat trim session-id.jsonl
    """
    if ctx.invoked_subcommand is None:
        # No subcommand - find latest sessions and show action menu
        _find_and_run_session_ui(
            session_id=None,
            agent_constraint='both',
            start_screen='action',
            select_target='action',
            results_title=' Select a session ',
        )


# Shared help text for find commands
_FIND_OPTIONS_COMMON = """
Options:
  KEYWORDS              Comma-separated keywords to search (AND logic)
  -g, --global          Search across all projects
  -n, --num-matches N   Number of matches to display (default: 10)
  --original            Show only original sessions
  --no-sub              Exclude sub-agent sessions
  --no-trim             Exclude trimmed sessions
  --no-cont             Exclude continued sessions
  --min-lines N         Only sessions with at least N lines
  --before TIMESTAMP    Sessions modified before (inclusive)
  --after TIMESTAMP     Sessions modified after (inclusive)
  --no-ui               Skip options menu, run search with CLI args directly
  --simple-ui           Use Rich table UI instead of Node UI"""

_FIND_OPTIONS_CODEX = _FIND_OPTIONS_COMMON.replace(
    "  --no-sub              Exclude sub-agent sessions\n", ""
)

_FIND_TIMESTAMP_HELP = """
Timestamp formats: YYYYMMDD, YYYY-MM-DD, MM/DD/YY, MM/DD/YYYY
                   Optional time: T16:45:23, T16:45, T16"""

_FIND_CTX_SETTINGS = {
    "ignore_unknown_options": True,
    "allow_extra_args": True,
    "allow_interspersed_args": False,
}


def _find_and_run_session_ui(
    session_id: str | None,
    agent_constraint: str,  # 'claude', 'codex', or 'both'
    start_screen: str,
    select_target: str | None = None,
    results_title: str | None = None,
    direct_action: str | None = None,
    action_kwargs: dict | None = None,
) -> None:
    """
    Find session(s) and run Node UI for the specified action.

    If session_id is provided, routes to session_menu_cli.
    Otherwise, finds latest sessions for current project/branch and shows UI.

    Args:
        session_id: Optional explicit session ID or path
        agent_constraint: 'claude', 'codex', or 'both'
        start_screen: Screen to show when single session found
        select_target: Screen to go to after selection (multiple sessions)
        results_title: Title for selection screen
        direct_action: If set, execute this action directly instead of showing UI
        action_kwargs: Optional kwargs to pass to action
    """
    import subprocess
    import sys
    from pathlib import Path

    from claude_code_tools.find_claude_session import (
        find_sessions as find_claude_sessions,
        get_claude_project_dir,
    )
    from claude_code_tools.find_codex_session import (
        find_sessions as find_codex_sessions,
        get_codex_home,
    )
    from claude_code_tools.node_menu_ui import run_node_menu_ui
    from claude_code_tools.session_menu_cli import execute_action
    from claude_code_tools.session_utils import default_export_path

    if session_id:
        # Route to session_menu_cli with appropriate start screen
        sys.argv = [
            sys.argv[0].replace('aichat', 'session-menu'),
            '--start-screen', start_screen,
            session_id,
        ]
        from claude_code_tools.session_menu_cli import main as menu_main
        menu_main()
        return

    # No session provided - find latest sessions for current project and branch
    current_branch = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True
        )
        current_branch = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    candidates = []

    # Find Claude sessions if applicable
    if agent_constraint in ('claude', 'both'):
        claude_sessions = find_claude_sessions([], global_search=False)
        if current_branch and claude_sessions:
            claude_sessions = [s for s in claude_sessions if s[7] == current_branch]

        if claude_sessions:
            s = claude_sessions[0]  # Most recent
            claude_dir = get_claude_project_dir()
            session_file = claude_dir / f"{s[0]}.jsonl"

            candidates.append({
                "agent": "claude",
                "agent_display": "Claude",
                "session_id": s[0],
                "mod_time": s[1],
                "create_time": s[2],
                "lines": s[3],
                "project": s[4],
                "preview": s[5],
                "cwd": s[6],
                "branch": s[7] or "",
                "file_path": str(session_file),
                "default_export_path": str(default_export_path(session_file, "claude")),
                "is_trimmed": s[8] if len(s) > 8 else False,
                "derivation_type": None,
                "is_sidechain": s[9] if len(s) > 9 else False,
            })

    # Find Codex sessions if applicable
    if agent_constraint in ('codex', 'both'):
        codex_home = get_codex_home()
        if codex_home.exists():
            codex_sessions = find_codex_sessions(codex_home, [], global_search=False)
            if current_branch and codex_sessions:
                codex_sessions = [
                    s for s in codex_sessions if s.get("branch") == current_branch
                ]

            if codex_sessions:
                s = codex_sessions[0]  # Most recent
                codex_file = Path(s.get("file_path", ""))
                candidates.append({
                    "agent": "codex",
                    "agent_display": "Codex",
                    "session_id": s["session_id"],
                    "mod_time": s.get("mod_time", 0),
                    "create_time": s.get("mod_time", 0),
                    "lines": s.get("lines", 0),
                    "project": s.get("project", ""),
                    "preview": s.get("preview", ""),
                    "cwd": s.get("cwd", ""),
                    "branch": s.get("branch", ""),
                    "file_path": s.get("file_path", ""),
                    "default_export_path": str(
                        default_export_path(codex_file, "codex")
                    ) if codex_file.exists() else "",
                    "is_trimmed": s.get("is_trimmed", False),
                    "derivation_type": None,
                    "is_sidechain": False,
                })

    if not candidates:
        agent_desc = {
            'claude': 'Claude',
            'codex': 'Codex',
            'both': 'Claude/Codex',
        }.get(agent_constraint, 'any')
        print(
            f"No {agent_desc} sessions found for current project/branch.",
            file=sys.stderr
        )
        sys.exit(1)

    # Handler for when user selects and acts
    def handler(sess, action, kwargs=None):
        session_file = Path(sess["file_path"])
        merged_kwargs = {**(action_kwargs or {}), **(kwargs or {})}
        execute_action(
            action,
            sess["agent"],
            session_file,
            sess["cwd"],
            action_kwargs=merged_kwargs if merged_kwargs else None,
        )

    rpc_path = str(Path(__file__).parent / "action_rpc.py")

    # If direct_action specified, execute it immediately for single session
    if direct_action and len(candidates) == 1:
        handler(candidates[0], direct_action, action_kwargs)
        return

    # Create handler that may execute direct_action after selection
    def selection_handler(sess, action, kwargs=None):
        if direct_action:
            # Execute direct_action instead of whatever came from UI
            handler(sess, direct_action, action_kwargs)
        else:
            handler(sess, action, kwargs)

    if len(candidates) == 1:
        # Single session - go directly to start_screen
        run_node_menu_ui(
            candidates,
            [],
            selection_handler,
            start_screen=start_screen,
            rpc_path=rpc_path,
            direct_action=direct_action,
        )
    else:
        # Multiple sessions - show selection first
        branch_info = f" on branch '{current_branch}'" if current_branch else ""
        agent_desc = {
            'claude': 'Claude',
            'codex': 'Codex',
            'both': 'Claude/Codex',
        }.get(agent_constraint, 'Claude/Codex')
        scope_text = (
            f"Most recent sessions from {agent_desc} in this project{branch_info}"
        )
        run_node_menu_ui(
            candidates,
            [],
            selection_handler,
            start_screen="results",
            select_target=select_target or start_screen,
            results_title=results_title or f" Select session for {start_screen} ",
            start_zoomed=True,
            scope_line=scope_text,
            rpc_path=rpc_path,
            direct_action=direct_action,
        )


@main.command("find", context_settings=_FIND_CTX_SETTINGS, add_help_option=False)
@click.pass_context
def find(ctx):
    """Find sessions across all agents (Claude Code, Codex, etc.)."""
    import sys
    sys.argv = [sys.argv[0].replace('aichat', 'find-session')] + ctx.args
    from claude_code_tools.find_session import main as find_main
    find_main()


find.__doc__ = f"""Find sessions across all agents (Claude Code, Codex, etc.).
{_FIND_OPTIONS_COMMON}
  --agents AGENT [...]  Limit to one or more agents (e.g., --agents claude,
                        --agents claude codex). Default: all.
{_FIND_TIMESTAMP_HELP}

Examples:
  aichat find "langroid,MCP"
  aichat find -g --min-lines 50 --agents claude
  aichat find --after 11/20/25 --before 11/25/25
"""


@main.command("find-claude", context_settings=_FIND_CTX_SETTINGS, add_help_option=False)
@click.pass_context
def find_claude(ctx):
    """Find Claude Code sessions by keywords."""
    import sys
    sys.argv = [sys.argv[0].replace('aichat', 'find-claude-session')] + ctx.args
    from claude_code_tools.find_claude_session import main as find_claude_main
    find_claude_main()


find_claude.__doc__ = f"""Find Claude Code sessions by keywords.
{_FIND_OPTIONS_COMMON}
{_FIND_TIMESTAMP_HELP}

Examples:
  aichat find-claude "bug fix"
  aichat find-claude -g --min-lines 100
  aichat find-claude --after 2025-11-01
"""


@main.command("find-codex", context_settings=_FIND_CTX_SETTINGS, add_help_option=False)
@click.pass_context
def find_codex(ctx):
    """Find Codex sessions by keywords."""
    import sys
    sys.argv = [sys.argv[0].replace('aichat', 'find-codex-session')] + ctx.args
    from claude_code_tools.find_codex_session import main as find_codex_main
    find_codex_main()


find_codex.__doc__ = f"""Find Codex sessions by keywords.
{_FIND_OPTIONS_CODEX}
{_FIND_TIMESTAMP_HELP}

Examples:
  aichat find-codex "error"
  aichat find-codex -g --after 11/15/25
"""


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
@click.argument("session", required=False)
@click.option("--simple-ui", is_flag=True, help="Use simple CLI trim instead of Node UI")
def trim(session, simple_ui):
    """Trim/resume session - shows menu of trim options.

    If no session ID provided, finds latest session for current project/branch.
    Opens Node UI with trim/resume options (trim+resume, smart-trim).
    Use --simple-ui for direct CLI trim.
    """
    import sys

    if simple_ui:
        if not session:
            print("Error: --simple-ui requires a session ID", file=sys.stderr)
            sys.exit(1)
        # Fall back to old trim-session CLI
        sys.argv = [sys.argv[0].replace('aichat', 'trim-session'), session]
        from claude_code_tools.trim_session import main as trim_main
        trim_main()
        return

    _find_and_run_session_ui(
        session_id=session,
        agent_constraint='both',
        start_screen='trim_menu',
        select_target='trim_menu',
        results_title=' Which session to trim? ',
    )


@main.command("smart-trim", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.pass_context
def smart_trim(ctx):
    """Smart trim using Claude SDK agents (EXPERIMENTAL).

    If no session ID provided, finds latest session for current project/branch.
    """
    import sys
    args = ctx.args
    session_id = args[0] if args and not args[0].startswith('-') else None

    if session_id:
        # Pass to existing smart_trim CLI
        sys.argv = [sys.argv[0].replace('aichat', 'smart-trim')] + args
        from claude_code_tools.smart_trim import main as smart_trim_main
        smart_trim_main()
    else:
        # Find latest session and execute smart_trim_resume directly
        _find_and_run_session_ui(
            session_id=None,
            agent_constraint='both',
            start_screen='trim_menu',  # Fallback if multiple sessions
            select_target='trim_menu',
            results_title=' Which session to smart-trim? ',
            direct_action='smart_trim_resume',
        )


@main.command("export", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.option("--agent", type=click.Choice(["claude", "codex"], case_sensitive=False), help="Force export with specific agent")
@click.argument("session", required=False)
@click.pass_context
def export_session(ctx, agent, session):
    """Export session to text/markdown format.

    If no session ID provided, finds latest session for current project/branch.
    Auto-detects session type and uses matching export command.
    Use --agent to override and force export with a specific agent.
    """
    import sys
    from pathlib import Path
    from claude_code_tools.session_utils import detect_agent_from_path, find_session_file

    if not session:
        # No session provided - find latest and export directly
        _find_and_run_session_ui(
            session_id=None,
            agent_constraint='both',
            start_screen='action',
            results_title=' Which session to export? ',
            direct_action='export',
        )
        return

    # Session provided - existing behavior
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
            print(f"\nDetected {detected_agent.upper()} session")
            print(f"Exporting with {export_agent.upper()} (user specified)")
        else:
            print(f"\nExporting with {export_agent.upper()} (user specified)")
    elif detected_agent:
        # Use detected agent
        export_agent = detected_agent
        print(f"\nDetected {detected_agent.upper()} session")
        print(f"Exporting with {export_agent.upper()}")
    else:
        # Default to Claude if cannot detect
        export_agent = "claude"
        print(f"\nCould not detect session type, defaulting to CLAUDE")

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
    """Export Claude Code session to text/markdown format.

    If no session ID provided, finds latest Claude session for current
    project/branch.
    """
    import sys
    args = ctx.args
    session_id = args[0] if args and not args[0].startswith('-') else None

    if session_id:
        # Pass to existing export CLI
        sys.argv = [sys.argv[0].replace('aichat', 'export-claude-session')] + args
        from claude_code_tools.export_claude_session import (
            main as export_claude_main,
        )
        export_claude_main()
    else:
        # Find latest Claude session and export directly
        _find_and_run_session_ui(
            session_id=None,
            agent_constraint='claude',
            start_screen='action',
            results_title=' Which Claude session to export? ',
            direct_action='export',
        )


@main.command("export-codex", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.pass_context
def export_codex(ctx):
    """Export Codex session to text/markdown format.

    If no session ID provided, finds latest Codex session for current
    project/branch.
    """
    import sys
    args = ctx.args
    session_id = args[0] if args and not args[0].startswith('-') else None

    if session_id:
        # Pass to existing export CLI
        sys.argv = [sys.argv[0].replace('aichat', 'export-codex-session')] + args
        from claude_code_tools.export_codex_session import (
            main as export_codex_main,
        )
        export_codex_main()
    else:
        # Find latest Codex session and export directly
        _find_and_run_session_ui(
            session_id=None,
            agent_constraint='codex',
            start_screen='action',
            results_title=' Which Codex session to export? ',
            direct_action='export',
        )


@main.command("delete", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.pass_context
def delete(ctx):
    """Delete a session file with safety confirmation."""
    import sys
    sys.argv = [sys.argv[0].replace('aichat', 'delete-session')] + ctx.args
    from claude_code_tools.delete_session import main as delete_main
    delete_main()


@main.command("resume", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.pass_context
def resume_session(ctx):
    """Resume a session with various options (resume, clone, trim, continue).

    If no session ID provided, finds latest session for current project/branch.
    Shows resume menu with options: resume as-is, clone, trim+resume,
    smart-trim, or continue with context.
    """
    args = ctx.args
    session_id = args[0] if args and not args[0].startswith('-') else None
    _find_and_run_session_ui(
        session_id=session_id,
        agent_constraint='both',
        start_screen='resume',
        select_target='resume',
        results_title=' Which session to resume? ',
    )


if __name__ == "__main__":
    main()
