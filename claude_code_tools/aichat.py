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


# =============================================================================
# Search Infrastructure Commands
# =============================================================================


@main.command("clear-index")
@click.option(
    "--index", "-i",
    type=click.Path(),
    default="~/.claude/search-index",
    help="Index directory (default: ~/.claude/search-index/)",
)
@click.option("--dry-run", "-n", is_flag=True, help="Show what would be deleted")
def clear_index(index, dry_run):
    """Clear the Tantivy search index.

    Deletes the entire index directory to allow a fresh rebuild.
    """
    import shutil
    from pathlib import Path

    index_path = Path(index).expanduser()

    if not index_path.exists():
        print(f"Index directory does not exist: {index_path}")
        return

    # Count files for info
    file_count = sum(1 for _ in index_path.rglob("*") if _.is_file())

    if dry_run:
        print(f"Dry run: would delete index at {index_path}")
        print(f"   {file_count} files would be removed")
    else:
        shutil.rmtree(index_path)
        print(f"✅ Cleared index at {index_path}")
        print(f"   {file_count} files removed")


@main.command("clear-exports")
@click.option("--verbose", "-v", is_flag=True, help="Show what's being deleted")
@click.option("--dry-run", "-n", is_flag=True, help="Show what would be deleted")
def clear_exports(verbose, dry_run):
    """Clear all exported session files from project directories.

    Finds export files in per-project directories:
    {project}/exported-sessions/{agent}/*.txt

    Use this before re-exporting to ensure a clean slate.
    """
    from claude_code_tools.export_all import (
        collect_sessions_to_export,
        extract_export_dir_from_session,
    )

    print("Scanning for export files to delete...")
    sessions = collect_sessions_to_export()
    print(f"Found {len(sessions)} sessions to check")

    deleted_count = 0
    dirs_cleaned = set()

    with click.progressbar(
        sessions,
        label="Scanning",
        show_pos=True,
        item_show_func=lambda x: x[0].name if x else "",
    ) as bar:
        for session_file, agent in bar:
            export_dir = extract_export_dir_from_session(session_file, agent=agent)
            if export_dir and export_dir.exists():
                export_file = export_dir / f"{session_file.stem}.txt"
                if export_file.exists():
                    if dry_run:
                        if verbose:
                            print(f"\nWould delete: {export_file}")
                    else:
                        if verbose:
                            print(f"\nDeleting: {export_file}")
                        export_file.unlink()
                    deleted_count += 1
                    dirs_cleaned.add(export_dir)

    if dry_run:
        print(f"\nDry run: would delete {deleted_count} files "
              f"from {len(dirs_cleaned)} directories")
    else:
        print(f"\n✅ Cleared {deleted_count} export files "
              f"from {len(dirs_cleaned)} directories")


@main.command("export-all")
@click.option("--force", "-f", is_flag=True, help="Re-export all (ignore mtime)")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress and failures")
def export_all(force, verbose):
    """Export all sessions with YAML front matter for indexing.

    Each session is exported to its own project directory:
    {project}/exported-sessions/{agent}/{session_id}.txt

    Skips sessions that haven't changed since last export (unless --force).
    """
    from claude_code_tools.export_all import (
        collect_sessions_to_export,
        export_single_session,
    )

    print("Collecting sessions...")
    sessions = collect_sessions_to_export()
    print(f"Found {len(sessions)} sessions to process")

    stats: dict = {
        "exported": 0,
        "skipped": 0,
        "failed": 0,
        "exported_files": [],
        "failures": [],
    }

    with click.progressbar(
        sessions,
        label="Exporting",
        show_pos=True,
        item_show_func=lambda x: x[0].name if x else "",
    ) as bar:
        for session_file, agent in bar:
            result = export_single_session(session_file, agent, force)

            if result["status"] == "exported":
                stats["exported"] += 1
                stats["exported_files"].append(result["export_file"])
            elif result["status"] == "skipped":
                stats["skipped"] += 1
                if result["export_file"]:
                    stats["exported_files"].append(result["export_file"])
            else:  # failed
                stats["failed"] += 1
                stats["failures"].append({
                    "session": str(session_file),
                    "agent": agent,
                    "error": result["error"],
                })

    print(f"\n✅ Export complete:")
    print(f"   Exported: {stats['exported']}")
    print(f"   Skipped:  {stats['skipped']} (up-to-date)")
    print(f"   Failed:   {stats['failed']}")
    print(f"   Total export files: {len(stats['exported_files'])}")

    if stats["failures"] and verbose:
        print(f"\n⚠️  Failures ({len(stats['failures'])}):")
        for failure in stats["failures"]:
            print(f"   {failure['session']}")
            print(f"      Error: {failure['error']}")


@main.command("build-index")
@click.option(
    "--index", "-i",
    type=click.Path(),
    default="~/.claude/search-index",
    help="Index directory (default: ~/.claude/search-index/)",
)
@click.option("--full", is_flag=True, help="Full rebuild (not incremental)")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress and failures")
def build_index(index, full, verbose):
    """Build Tantivy search index from exported sessions.

    Finds exported .txt files in per-project directories and indexes them
    for full-text search. Incremental by default (only indexes new/changed).

    Export files are expected at: {project}/exported-sessions/{agent}/*.txt
    """
    from pathlib import Path
    from claude_code_tools.search_index import SessionIndex
    from claude_code_tools.export_all import (
        extract_export_dir_from_session,
        find_all_claude_sessions,
        find_all_codex_sessions,
        should_export_session,
    )
    from claude_code_tools.session_utils import get_claude_home, get_codex_home

    index_path = Path(index).expanduser()
    claude_home = get_claude_home()
    codex_home = get_codex_home()

    print("Scanning for export files...")

    # Collect all export files that exist
    export_files: list[Path] = []

    # Find Claude session exports
    claude_sessions = find_all_claude_sessions(claude_home)
    for session_file in claude_sessions:
        if not should_export_session(session_file, agent="claude"):
            continue
        export_dir = extract_export_dir_from_session(session_file, agent="claude")
        if export_dir:
            export_file = export_dir / f"{session_file.stem}.txt"
            if export_file.exists():
                export_files.append(export_file)

    # Find Codex session exports
    codex_sessions = find_all_codex_sessions(codex_home)
    for session_file in codex_sessions:
        if not should_export_session(session_file, agent="codex"):
            continue
        export_dir = extract_export_dir_from_session(session_file, agent="codex")
        if export_dir:
            export_file = export_dir / f"{session_file.stem}.txt"
            if export_file.exists():
                export_files.append(export_file)

    if not export_files:
        print("No export files found.")
        print("Run 'aichat export-all' first to export sessions.")
        return

    print(f"Found {len(export_files)} export files")
    print(f"Building index at: {index_path}")

    idx = SessionIndex(index_path)
    writer = idx.get_writer()
    incremental = not full

    stats: dict = {
        "indexed": 0,
        "skipped": 0,
        "failed": 0,
        "failures": [],
    }

    with click.progressbar(
        export_files,
        label="Indexing",
        show_pos=True,
        item_show_func=lambda x: x.name if x else "",
    ) as bar:
        for export_file in bar:
            result = idx.index_single_file(export_file, writer, incremental)
            if result["status"] == "indexed":
                stats["indexed"] += 1
            elif result["status"] == "skipped":
                stats["skipped"] += 1
            else:
                stats["failed"] += 1
                stats["failures"].append({
                    "file": str(export_file),
                    "error": result["error"],
                })

    idx.commit_and_reload(writer)

    print(f"\n✅ Index build complete:")
    print(f"   Indexed: {stats['indexed']}")
    print(f"   Skipped: {stats['skipped']} (unchanged)")
    print(f"   Failed:  {stats['failed']}")

    if stats["failures"] and verbose:
        print(f"\n⚠️  Failures ({len(stats['failures'])}):")
        for failure in stats["failures"]:
            print(f"   {failure['file']}")
            print(f"      Error: {failure['error']}")


@main.command("search")
@click.argument("query", required=False, default="")
@click.option(
    "--index", "-i",
    type=click.Path(),
    default="~/.claude/search-index",
    help="Index directory",
)
@click.option("-n", "--limit", default=20, help="Max results")
@click.option("--project", "-p", help="Filter to project name")
def search(query, index, limit, project):
    """Search sessions using Tantivy full-text index (POC).

    If no query provided, shows recent sessions.
    """
    from pathlib import Path
    from claude_code_tools.search_index import SessionIndex

    index_path = Path(index).expanduser()

    if not index_path.exists():
        print(f"Error: Index not found at: {index_path}")
        print("Run 'aichat export-all && aichat build-index' first.")
        return

    idx = SessionIndex(index_path)

    if query:
        print(f"Searching for: {query}\n")
        results = idx.search(query, limit=limit, project=project)
    else:
        print("Recent sessions:\n")
        results = idx.get_recent(limit=limit, project=project)

    if not results:
        print("No results found.")
        return

    # Simple CLI output for POC
    for i, r in enumerate(results, 1):
        agent_icon = "●" if r["agent"] == "claude" else "■"
        lines = r.get("lines", 0)
        print(f"{i:2}. {agent_icon} {r['project']} | {r['session_id'][:12]}... | {lines}L")
        print(f"    {r['snippet'][:80]}...")
        print()


@main.command("search-ui")
def search_ui():
    """Launch Rust TUI for session search with Node action menu handoff.

    This is a POC demonstrating Rust → Node handoff:
    1. Rust TUI displays sessions from Tantivy index
    2. User selects a session
    3. Selected session is passed to Node action menu
    4. Escape from Node menu returns to Rust TUI
    5. Quit (q/Esc) from Rust TUI exits
    """
    import json
    import os
    import subprocess
    import tempfile
    from pathlib import Path

    # Find Rust binary
    rust_binary = Path(__file__).parent.parent / "rust-search-ui" / "target" / "release" / "session_search"
    if not rust_binary.exists():
        print(f"Error: Rust binary not found at: {rust_binary}")
        print("Build it with: cd rust-search-ui && cargo build --release")
        return

    # Import once outside the loop
    from claude_code_tools.node_menu_ui import run_node_menu_ui
    from claude_code_tools.session_menu_cli import execute_action

    # RPC path for action execution
    rpc_path = str(Path(__file__).parent / "action_rpc.py")

    def action_handler(sess, action, kwargs):
        """Handle action from Node menu."""
        agent = sess.get("agent", "claude")
        file_path = sess.get("file_path")
        cwd = sess.get("cwd") or "."

        if not file_path:
            print(f"Error: No file_path for session {sess.get('session_id')}")
            return

        execute_action(
            action=action,
            agent=agent,
            session_file=Path(file_path),
            project_path=cwd,
            action_kwargs=kwargs,
        )

    # Main loop: Rust TUI → Node menu → back to Rust TUI
    while True:
        # Create temp file for IPC
        fd, out_path = tempfile.mkstemp(suffix="-rust-ui.json")
        os.close(fd)

        # Run Rust TUI (interactive - needs TTY)
        try:
            result = subprocess.run([str(rust_binary), out_path])
        except Exception as e:
            print(f"Error running Rust TUI: {e}")
            try:
                os.unlink(out_path)
            except Exception:
                pass
            return

        if result.returncode != 0:
            try:
                os.unlink(out_path)
            except Exception:
                pass
            return

        # Read JSON from temp file
        try:
            content = Path(out_path).read_text().strip()
        except Exception:
            content = ""
        finally:
            try:
                os.unlink(out_path)
            except Exception:
                pass

        if not content:
            # User quit without selecting - exit the loop
            return

        try:
            selected = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"Error parsing Rust output: {e}")
            print(f"Output was: {content[:200]}")
            return

        # Convert to session format expected by Node menu
        session = {
            "session_id": selected.get("session_id", ""),
            "agent": selected.get("agent", "claude"),
            "agent_display": selected.get("agent", "claude").title(),
            "project": selected.get("project", ""),
            "branch": selected.get("branch", ""),
            "lines": selected.get("lines", 0),
            "file_path": selected.get("export_path", ""),
            "cwd": None,
        }

        # Extract cwd from export_path metadata if needed
        export_path = selected.get("export_path", "")
        if export_path:
            try:
                with open(export_path, "r") as f:
                    file_content = f.read(2000)
                    if file_content.startswith("---\n"):
                        end_idx = file_content.find("\n---\n", 4)
                        if end_idx != -1:
                            import yaml
                            metadata = yaml.safe_load(file_content[4:end_idx])
                            if metadata:
                                session["cwd"] = metadata.get("cwd")
                                session["file_path"] = metadata.get("file_path", export_path)
            except Exception:
                pass

        print(f"Selected: {session['project']} / {session['session_id'][:12]}...")

        # Launch Node action menu - returns None normally, loops back on Escape
        run_node_menu_ui(
            sessions=[session],
            keywords=[],
            action_handler=action_handler,
            start_action=True,
            focus_session_id=session["session_id"],
            rpc_path=rpc_path,
        )
        # After Node menu exits (Escape or action complete), loop back to Rust TUI


if __name__ == "__main__":
    main()
