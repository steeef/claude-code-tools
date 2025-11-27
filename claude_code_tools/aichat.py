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


@main.command("resume", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "allow_interspersed_args": False})
@click.pass_context
def resume_session(ctx):
    """Resume a session with various options (resume, clone, trim, continue).

    If no session ID provided, finds latest session for current project/branch.
    Shows resume menu with options: resume as-is, clone, trim+resume,
    smart-trim, or continue with context.
    """
    import sys
    from pathlib import Path

    # Check if session argument was provided
    args = ctx.args
    session_provided = args and not args[0].startswith('-')

    if session_provided:
        # Route to session_menu_cli with --start-screen resume
        sys.argv = [sys.argv[0].replace('aichat', 'session-menu'), '--start-screen', 'resume'] + args
        from claude_code_tools.session_menu_cli import main as menu_main
        menu_main()
    else:
        # No session provided - find latest sessions for current project and branch
        import subprocess
        from claude_code_tools.find_claude_session import (
            find_sessions as find_claude_sessions,
        )
        from claude_code_tools.find_codex_session import (
            find_sessions as find_codex_sessions,
            get_codex_home,
        )
        from claude_code_tools.node_menu_ui import run_node_menu_ui
        from claude_code_tools.session_menu_cli import execute_action

        # Get current git branch
        current_branch = None
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, check=True
            )
            current_branch = result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # Find Claude sessions for current project
        claude_sessions = find_claude_sessions([], global_search=False)

        # Filter by current branch if available
        if current_branch and claude_sessions:
            # Claude tuple index 7 is git_branch
            claude_sessions = [s for s in claude_sessions if s[7] == current_branch]

        # Find Codex sessions for current project
        codex_home = get_codex_home()
        codex_sessions = []
        if codex_home.exists():
            codex_sessions = find_codex_sessions(codex_home, [], global_search=False)
            # Filter by current branch if available
            if current_branch and codex_sessions:
                codex_sessions = [s for s in codex_sessions if s.get("branch") == current_branch]

        # Build session dicts for Node UI
        candidates = []

        from claude_code_tools.session_utils import default_export_path

        if claude_sessions:
            # Claude returns tuple: (session_id, mod_time, create_time, line_count,
            #                        project_name, preview, project_path, git_branch, is_trimmed, is_sidechain)
            s = claude_sessions[0]  # Most recent
            # Get the actual file path
            from claude_code_tools.find_claude_session import get_claude_project_dir
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

        if codex_sessions:
            # Codex returns dict with keys: session_id, project, branch,
            #                               lines, preview, cwd, file_path, mod_time, is_trimmed
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
                "default_export_path": str(default_export_path(codex_file, "codex")) if codex_file.exists() else "",
                "is_trimmed": s.get("is_trimmed", False),
                "derivation_type": None,
                "is_sidechain": False,
            })

        if not candidates:
            print("No sessions found for current project/branch.", file=sys.stderr)
            sys.exit(1)

        # Handler for when user selects and resumes
        def handler(sess, action, kwargs=None):
            session_file = Path(sess["file_path"])
            execute_action(
                action,
                sess["agent"],
                session_file,
                sess["cwd"],
                action_kwargs=kwargs,
            )

        rpc_path = str(Path(__file__).parent / "action_rpc.py")

        if len(candidates) == 1:
            # Single session - go directly to resume menu
            run_node_menu_ui(
                candidates,
                [],
                handler,
                start_screen="resume",
                rpc_path=rpc_path,
            )
        else:
            # Multiple sessions - show selection first
            branch_info = f" on branch '{current_branch}'" if current_branch else ""
            scope_text = f"Most recent sessions from Claude/Codex in this project{branch_info}"
            run_node_menu_ui(
                candidates,
                [],
                handler,
                start_screen="results",
                select_target="resume",
                results_title=" Which session to resume? ",
                start_zoomed=True,
                scope_line=scope_text,
                rpc_path=rpc_path,
            )


if __name__ == "__main__":
    main()
