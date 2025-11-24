#!/usr/bin/env python3
"""
Unified session finder - search across multiple coding agents (Claude Code, Codex, etc.)

Usage:
    find-session [keywords] [OPTIONS]
    fs [keywords] [OPTIONS]  # via shell wrapper

Examples:
    find-session "langroid,MCP"      # Search all agents in current project
    find-session -g                  # Show all sessions across all projects
    find-session "bug" --agents claude  # Search only Claude sessions
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
import termios
import tty

# Import search functions from existing tools
from claude_code_tools.find_claude_session import (
    find_sessions as find_claude_sessions,
    resume_session as resume_claude_session,
    get_session_file_path as get_claude_session_file_path,
    copy_session_file as copy_claude_session_file,
    clone_session as clone_claude_session,
    handle_export_session as handle_export_claude_session,
    is_sidechain_session,
    is_malformed_session,
)
from claude_code_tools.find_codex_session import (
    find_sessions as find_codex_sessions,
    resume_session as resume_codex_session,
    get_codex_home,
    copy_session_file as copy_codex_session_file,
    clone_session as clone_codex_session,
    handle_export_session as handle_export_codex_session,
)
from claude_code_tools.session_menu import (
    show_action_menu as menu_show_action_menu,
    show_resume_submenu as menu_show_resume_submenu,
    prompt_suppress_options as menu_prompt_suppress_options,
)
from claude_code_tools.node_menu_ui import run_node_menu_ui
from claude_code_tools.trim_session import (
    trim_and_create_session,
    is_trimmed_session,
    get_session_derivation_type,
)
from claude_code_tools.session_utils import format_session_id_display

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    from claude_code_tools.session_tui import run_session_tui

    TUI_AVAILABLE = True
except ImportError:
    TUI_AVAILABLE = False


@dataclass
class AgentConfig:
    """Configuration for a coding agent."""

    name: str  # Internal name (e.g., "claude", "codex")
    display_name: str  # Display name (e.g., "Claude", "Codex")
    home_dir: Optional[str]  # Custom home directory (None = default)
    enabled: bool = True


def get_default_agents() -> List[AgentConfig]:
    """Get default agent configurations."""
    return [
        AgentConfig(name="claude", display_name="Claude", home_dir=None),
        AgentConfig(name="codex", display_name="Codex", home_dir=None),
    ]


def load_config() -> List[AgentConfig]:
    """Load agent configuration from config file or use defaults."""
    config_path = Path.home() / ".config" / "find-session" / "config.json"

    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
                agents = []
                for agent_data in data.get("agents", []):
                    agents.append(
                        AgentConfig(
                            name=agent_data["name"],
                            display_name=agent_data.get(
                                "display_name", agent_data["name"].title()
                            ),
                            home_dir=agent_data.get("home_dir"),
                            enabled=agent_data.get("enabled", True),
                        )
                    )
                return agents
        except (json.JSONDecodeError, KeyError, IOError):
            pass

    # Return defaults if config doesn't exist or is invalid
    return get_default_agents()


def build_scope_lines(args) -> tuple[str, str | None]:
    """Return scope line and optional tip line mirroring Rich UI messaging."""
    if args.original:
        return (
            "Showing: Original sessions only (excluding trimmed, continued, and sub-agent sessions)",
            None,
        )

    excluded_types = []
    if args.no_sub:
        excluded_types.append("sub-agent")
    if args.no_trim:
        excluded_types.append("trimmed")
    if args.no_cont:
        excluded_types.append("continued")

    if excluded_types:
        excluded_str = ", ".join(excluded_types)
        return (f"Showing: All sessions except {excluded_str}", None)

    return (
        "Showing: All session types (original, trimmed, continued, and sub-agent)",
        "Tip: Use --no-sub, --no-trim, or --no-cont to exclude specific types",
    )


def search_all_agents(
    keywords: List[str],
    global_search: bool = False,
    num_matches: int = 10,
    agents: Optional[List[str]] = None,
    claude_home: Optional[str] = None,
    codex_home: Optional[str] = None,
    original_only: bool = False,
    no_sub: bool = False,
    no_trim: bool = False,
    no_cont: bool = False,
) -> List[dict]:
    """
    Search sessions across all enabled agents.

    Args:
        keywords: List of keywords to search for
        global_search: Search across all projects
        num_matches: Number of matches to return
        agents: List of agent names to search
        claude_home: Claude home directory
        codex_home: Codex home directory
        original_only: Only return original sessions (excludes trimmed, continued, and sub-agent)
        no_sub: Exclude sub-agent sessions
        no_trim: Exclude trimmed sessions
        no_cont: Exclude continued sessions

    Returns list of dicts with agent metadata added.
    """
    agent_configs = load_config()

    # Filter by requested agents if specified
    if agents:
        agent_configs = [a for a in agent_configs if a.name in agents]

    # Filter by enabled agents
    agent_configs = [a for a in agent_configs if a.enabled]

    all_sessions = []

    for agent_config in agent_configs:
        if agent_config.name == "claude":
            # Search Claude sessions
            home = claude_home or agent_config.home_dir
            sessions = find_claude_sessions(
                keywords,
                global_search=global_search,
                claude_home=home,
                original_only=original_only,
                no_sub=no_sub,
                no_trim=no_trim,
                no_cont=no_cont,
            )

            # Add agent metadata to each session
            for session in sessions:
                session_id = session[0]
                cwd = session[6]

                # Get file path and check if trimmed
                file_path = Path(
                    get_claude_session_file_path(session_id, cwd, claude_home=home)
                )
                is_trimmed = is_trimmed_session(file_path)
                derivation_type = get_session_derivation_type(file_path)

                # Skip if original_only and session is trimmed
                if original_only and is_trimmed:
                    continue

                # Check if session is sidechain (sub-agent)
                is_sidechain = is_sidechain_session(file_path)

                # Skip malformed Claude sessions (missing metadata, cannot resume)
                if is_malformed_session(file_path):
                    continue

                session_dict = {
                    "agent": "claude",
                    "agent_display": agent_config.display_name,
                    "session_id": session_id,
                    "mod_time": session[1],
                    "create_time": session[2],
                    "lines": session[3],
                    "project": session[4],
                    "preview": session[5],
                    "cwd": cwd,
                    "branch": session[7] if len(session) > 7 else "",
                    "claude_home": home,
                    "is_trimmed": is_trimmed,
                    "derivation_type": derivation_type,
                    "is_sidechain": is_sidechain,
                }
                all_sessions.append(session_dict)

        elif agent_config.name == "codex":
            # Search Codex sessions
            home = codex_home or agent_config.home_dir
            codex_home_path = get_codex_home(home)

            if codex_home_path.exists():
                sessions = find_codex_sessions(
                    codex_home_path,
                    keywords,
                    num_matches=num_matches * 2,  # Get more for merging
                    global_search=global_search,
                    original_only=original_only,
                    no_sub=no_sub,
                    no_trim=no_trim,
                    no_cont=no_cont,
                )

                # Add agent metadata to each session
                for session in sessions:
                    file_path = Path(session.get("file_path", ""))
                    is_trimmed = is_trimmed_session(file_path)
                    derivation_type = get_session_derivation_type(file_path)

                    # Skip if original_only and session is trimmed
                    if original_only and is_trimmed:
                        continue

                    session_dict = {
                        "agent": "codex",
                        "agent_display": agent_config.display_name,
                        "session_id": session["session_id"],
                        "mod_time": session["mod_time"],
                        "create_time": session.get("mod_time"),  # Codex doesn't separate these
                        "lines": session["lines"],
                        "project": session["project"],
                        "preview": session["preview"],
                        "cwd": session["cwd"],
                        "branch": session.get("branch", ""),
                        "file_path": session.get("file_path", ""),
                        "is_trimmed": is_trimmed,
                        "derivation_type": derivation_type,
                        "is_sidechain": False,  # Codex doesn't have sidechain sessions
                    }
                    all_sessions.append(session_dict)

    # Sort by modification time (newest first) and limit
    all_sessions.sort(key=lambda x: x["mod_time"], reverse=True)
    return all_sessions[:num_matches]


def display_interactive_ui(
    sessions: List[dict], keywords: List[str], stderr_mode: bool = False, num_matches: int = 10
) -> Optional[dict]:
    """Display unified session selection UI."""
    if not RICH_AVAILABLE:
        return None

    # Use stderr console if in stderr mode
    ui_console = Console(file=sys.stderr) if stderr_mode else Console()

    # Limit to specified number of sessions
    display_sessions = sessions[:num_matches]

    if not display_sessions:
        ui_console.print("[red]No sessions found[/red]")
        return None

    # Create table
    title = (
        f"Sessions matching: {', '.join(keywords)}" if keywords else "All sessions"
    )
    table = Table(
        title=title, box=box.ROUNDED, show_header=True, header_style="bold cyan"
    )

    table.add_column("#", style="bold yellow", width=3)
    table.add_column("Agent", style="magenta", width=6)
    table.add_column("Session ID", style="dim", width=18)
    table.add_column("Project", style="green")
    table.add_column("Branch", style="cyan")
    table.add_column("Date", style="blue")
    table.add_column("Lines", style="cyan", justify="right", width=6)
    table.add_column("Last User Message", style="white", max_width=50, overflow="fold")

    for idx, session in enumerate(display_sessions, 1):
        # Format date from mod_time
        from datetime import datetime

        mod_time = session["mod_time"]
        date_str = datetime.fromtimestamp(mod_time).strftime("%m/%d %H:%M")

        branch_display = session.get("branch", "") or "N/A"

        # Format session ID with annotations using centralized helper
        derivation_type = session.get("derivation_type")
        session_id_display = format_session_id_display(
            session["session_id"],
            is_trimmed=(derivation_type == "trimmed"),
            is_continued=(derivation_type == "continued"),
            is_sidechain=session.get("is_sidechain", False),
            truncate_length=8,
        )

        table.add_row(
            str(idx),
            session["agent_display"],
            session_id_display,
            session["project"],
            branch_display,
            date_str,
            str(session["lines"]),
            session["preview"],
        )

    ui_console.print(table)

    # Show footnotes if any sessions are derived or sidechain
    has_trimmed = any(s.get("derivation_type") == "trimmed" for s in display_sessions)
    has_continued = any(s.get("derivation_type") == "continued" for s in display_sessions)
    has_sidechain = any(s.get("is_sidechain", False) for s in display_sessions)
    if has_trimmed or has_continued or has_sidechain:
        footnotes = []
        if has_trimmed:
            footnotes.append("(t) = Trimmed session")
        if has_continued:
            footnotes.append("(c) = Continued session")
        if has_sidechain:
            footnotes.append("(sub) = Sub-agent session (not directly resumable)")
        ui_console.print("[dim]" + " | ".join(footnotes) + "[/dim]")

    # Auto-select if only one result
    if len(display_sessions) == 1:
        ui_console.print(f"\n[yellow]Auto-selecting only match: {display_sessions[0]['session_id'][:16]}...[/yellow]")
        return display_sessions[0]

    ui_console.print("\n[bold]Select a session:[/bold]")
    ui_console.print(f"  • Enter number (1-{len(display_sessions)}) to select")
    ui_console.print("  • Press Enter to cancel\n")

    while True:
        try:
            from rich.prompt import Prompt

            choice = Prompt.ask(
                "Your choice", default="", show_default=False, console=ui_console
            )

            # Handle empty input - cancel
            if not choice or not choice.strip():
                ui_console.print("[yellow]Cancelled[/yellow]")
                return None

            idx = int(choice) - 1
            if 0 <= idx < len(display_sessions):
                return display_sessions[idx]
            else:
                ui_console.print("[red]Invalid choice. Please try again.[/red]")

        except KeyboardInterrupt:
            ui_console.print("\n[yellow]Cancelled[/yellow]")
            return None
        except EOFError:
            ui_console.print("\n[yellow]Cancelled (EOF)[/yellow]")
            return None
        except ValueError:
            ui_console.print("[red]Invalid choice. Please try again.[/red]")


def show_resume_submenu(stderr_mode: bool = False) -> Optional[str]:
    """Show resume options submenu."""
    return menu_show_resume_submenu(stderr_mode=stderr_mode)


def prompt_suppress_options(
    stderr_mode: bool = False
) -> Optional[Tuple[Optional[str], int, Optional[int]]]:
    """
    Prompt user for suppress-tool-results options.

    Returns:
        Tuple of (tools, threshold, trim_assistant_messages) or None if cancelled
    """
    return menu_prompt_suppress_options(stderr_mode=stderr_mode)


def append_to_codex_history(
    session_id: str, first_user_msg: str, codex_home: str
) -> None:
    """
    Append session to Codex history.jsonl file.

    Args:
        session_id: Session UUID
        first_user_msg: First user message text
        codex_home: Codex home directory
    """
    history_file = Path(codex_home) / "history.jsonl"
    history_entry = {
        "session_id": session_id,
        "ts": int(time.time()),
        "text": first_user_msg[:500],  # Limit to 500 chars
    }

    with open(history_file, "a") as f:
        f.write(json.dumps(history_entry) + "\n")


def extract_first_user_message(session_file: Path, agent: str) -> str:
    """
    Extract first user message from session file.

    Args:
        session_file: Path to session file
        agent: Agent type ('claude' or 'codex')

    Returns:
        First user message text
    """
    with open(session_file, "r") as f:
        for line in f:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            if agent == "claude":
                if data.get("type") == "user":
                    content = data.get("message", {}).get("content")
                    if isinstance(content, str):
                        return content
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                return item.get("text", "")
            elif agent == "codex":
                if data.get("type") == "response_item":
                    payload = data.get("payload", {})
                    if payload.get("type") == "message":
                        role = payload.get("role")
                        if role == "user":
                            # Codex stores text in content array
                            content = payload.get("content", [])
                            if content and isinstance(content, list):
                                for item in content:
                                    if isinstance(item, dict):
                                        text = item.get("text", "")
                                        # Skip environment_context, get actual user message
                                        if text and "<environment_context>" not in text:
                                            return text
                            # If content structure is different, try payload.text
                            if payload.get("text"):
                                return payload.get("text")
                            # Otherwise continue to next message

    return "Suppressed session"


def handle_suppress_resume(
    session: dict,
    tools: Optional[str],
    threshold: int,
    trim_assistant_messages: Optional[int] = None,
    shell_mode: bool = False
) -> None:
    """
    Suppress tool results and resume session.

    Args:
        session: Session dict
        tools: Tool names to suppress (comma-separated) or None for all
        threshold: Length threshold
        trim_assistant_messages: Optional assistant message trimming
        shell_mode: Whether in shell mode
    """
    agent = session["agent"]

    # Get session file path based on agent type
    if agent == "claude":
        session_file = Path(
            get_claude_session_file_path(
                session["session_id"],
                session["cwd"],
                claude_home=session.get("claude_home"),
            )
        )
    else:  # codex
        session_file = Path(session["file_path"])

    output = sys.stderr if shell_mode else sys.stdout
    print(f"\n🔧 Trimming session...", file=output)

    # Parse tools into set if provided
    target_tools = None
    if tools:
        target_tools = {tool.strip().lower() for tool in tools.split(",")}

    try:
        # Use helper function to trim and create new session
        result = trim_and_create_session(
            agent,
            session_file,
            target_tools,
            threshold,
            trim_assistant_messages=trim_assistant_messages
        )
    except Exception as e:
        print(f"❌ Error trimming session: {e}", file=output)
        return

    new_session_id = result["session_id"]
    new_session_file = result["output_file"]

    print(f"\n{'='*70}", file=output)
    print(f"✅ TRIM COMPLETE", file=output)
    print(f"{'='*70}", file=output)
    print(f"📁 New session file created:", file=output)
    print(f"   {new_session_file}", file=output)
    print(f"🆔 New session UUID: {new_session_id}", file=output)
    print(
        f"📊 Trimmed {result['num_tools_trimmed']} tool results, "
        f"{result['num_assistant_trimmed']} assistant messages, "
        f"saved ~{result['tokens_saved']:,} tokens",
        file=output,
    )

    # For Codex, append to history.jsonl
    if agent == "codex":
        # Get first user message from original session
        first_msg = extract_first_user_message(session_file, agent)

        # Append to history
        codex_home = get_codex_home()
        history_file = Path(codex_home) / "history.jsonl"
        append_to_codex_history(new_session_id, first_msg, codex_home)
        print(f"📝 Added entry to Codex history:", file=output)
        print(f"   {history_file}", file=output)

    print(f"\n🚀 Resuming suppressed session: {new_session_id[:16]}...", file=output)
    print(f"{'='*70}\n", file=output)

    # Resume the new session
    if agent == "claude":
        resume_claude_session(new_session_id, session["cwd"], shell_mode)
    elif agent == "codex":
        resume_codex_session(new_session_id, session["cwd"], shell_mode)


def show_action_menu(session: dict, stderr_mode: bool = False) -> Optional[str]:
    """Show action menu for selected session."""
    return menu_show_action_menu(
        session_id=session['session_id'],
        agent=session.get('agent', 'unknown'),
        project_name=session['project'],
        git_branch=session.get('branch'),
        is_sidechain=session.get('is_sidechain', False),
        stderr_mode=stderr_mode,
    )


def create_action_handler(
    shell_mode: bool = False, nonlaunch_flag: Optional[dict] = None
):
    """Create an action handler for the TUI or Node UI."""

    def action_handler(session, action: str, kwargs: Optional[dict] = None) -> None:
        """Handle actions from the UI - session can be tuple or dict."""
        # Convert session to dict if it's a tuple or dict-like
        if isinstance(session, dict):
            session_dict = session
        else:
            # Shouldn't happen in unified find, but handle gracefully
            session_dict = {"session_id": str(session), "agent": "unknown"}

        handle_action(
            session_dict, action, shell_mode=shell_mode, action_kwargs=kwargs or {}
        )

        if nonlaunch_flag is not None and action in {"path", "copy", "export"}:
            nonlaunch_flag["done"] = True
            nonlaunch_flag["session_id"] = session_dict.get("session_id")

    return action_handler


def handle_action(
    session: dict, action: str, shell_mode: bool = False, action_kwargs: Optional[dict] = None
) -> None:
    """Handle the selected action based on agent type."""
    agent = session["agent"]
    action_kwargs = action_kwargs or {}

    if action == "resume":
        if agent == "claude":
            resume_claude_session(
                session["session_id"],
                session["cwd"],
                shell_mode=shell_mode,
                claude_home=session.get("claude_home"),
            )
        elif agent == "codex":
            resume_codex_session(
                session["session_id"], session["cwd"], shell_mode=shell_mode
            )

    elif action == "suppress_resume":
        # Use provided options when available, otherwise prompt
        tools = action_kwargs.get("tools")
        threshold = action_kwargs.get("threshold")
        trim_assistant = action_kwargs.get("trim_assistant")
        if tools is None and threshold is None and trim_assistant is None:
            options = prompt_suppress_options(stderr_mode=shell_mode)
            if options:
                tools, threshold, trim_assistant = options
            else:
                return
        handle_suppress_resume(
            session, tools, threshold or 500, trim_assistant, shell_mode
        )

    elif action == "path":
        if agent == "claude":
            file_path = get_claude_session_file_path(
                session["session_id"],
                session["cwd"],
                claude_home=session.get("claude_home"),
            )
            print(f"\nSession file path:")
            print(file_path)
        elif agent == "codex":
            print(f"\nSession file path:")
            print(session.get("file_path", "Unknown"))

    elif action == "copy":
        if agent == "claude":
            file_path = get_claude_session_file_path(
                session["session_id"],
                session["cwd"],
                claude_home=session.get("claude_home"),
            )
            copy_claude_session_file(file_path)
        elif agent == "codex":
            copy_codex_session_file(session.get("file_path", ""))

    elif action == "clone":
        if agent == "claude":
            clone_claude_session(
                session["session_id"],
                session["cwd"],
                shell_mode=shell_mode,
                claude_home=session.get("claude_home"),
            )
        elif agent == "codex":
            clone_codex_session(
                session.get("file_path", ""),
                session["session_id"],
                session["cwd"],
                shell_mode=shell_mode,
            )

    elif action == "export":
        if agent == "claude":
            file_path = get_claude_session_file_path(
                session["session_id"],
                session["cwd"],
                claude_home=session.get("claude_home"),
            )
            handle_export_claude_session(file_path)
        elif agent == "codex":
            handle_export_codex_session(session.get("file_path", ""))

    elif action == "continue":
        # Continue with context in fresh session
        from claude_code_tools.session_utils import continue_with_options

        # Get file path based on agent type
        if agent == "claude":
            file_path = get_claude_session_file_path(
                session["session_id"],
                session["cwd"],
                claude_home=session.get("claude_home"),
            )
        else:
            # Codex session
            file_path = session["file_path"]

        continue_with_options(
            file_path,
            agent,
            claude_home=session.get("claude_home"),
            codex_home=session.get("codex_home")
        )


def main():
    parser = argparse.ArgumentParser(
        description="Unified session finder - search across multiple coding agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    find-session "langroid,MCP"           # Search all agents in current project
    find-session -g                       # Show all sessions across all projects
    find-session "bug" --agents claude    # Search only Claude sessions
    find-session "error" --agents codex   # Search only Codex sessions
        """,
    )
    parser.add_argument(
        "keywords",
        nargs="?",
        default="",
        help="Comma-separated keywords to search (AND logic). If omitted, shows all sessions.",
    )
    parser.add_argument(
        "-g",
        "--global",
        dest="global_search",
        action="store_true",
        help="Search across all projects, not just the current one",
    )
    parser.add_argument(
        "-n",
        "--num-matches",
        type=int,
        default=10,
        help="Number of matching sessions to display (default: 10)",
    )
    parser.add_argument(
        "--agents",
        nargs="+",
        choices=["claude", "codex"],
        help="Limit search to specific agents (default: all)",
    )
    parser.add_argument(
        "--shell",
        action="store_true",
        help="Output shell commands for evaluation (for use with shell function)",
    )
    parser.add_argument(
        "--claude-home", type=str, help="Path to Claude home directory (default: ~/.claude)"
    )
    parser.add_argument(
        "--codex-home", type=str, help="Path to Codex home directory (default: ~/.codex)"
    )
    parser.add_argument(
        "--original",
        action="store_true",
        help="Show only original sessions (excludes trimmed, continued, and sub-agent sessions)",
    )
    parser.add_argument(
        "--no-sub",
        action="store_true",
        help="Exclude sub-agent sessions from results",
    )
    parser.add_argument(
        "--no-trim",
        action="store_true",
        help="Exclude trimmed sessions from results",
    )
    parser.add_argument(
        "--no-cont",
        action="store_true",
        help="Exclude continued sessions from results",
    )
    parser.add_argument(
        "--altui",
        action="store_true",
        help="Use alternative UI (switches between Rich table and Textual TUI)",
    )

    args = parser.parse_args()

    # Parse keywords
    keywords = (
        [k.strip() for k in args.keywords.split(",") if k.strip()]
        if args.keywords
        else []
    )

    scope_line, tip_line = build_scope_lines(args)
    print(scope_line, file=sys.stderr)
    if tip_line:
        print(tip_line, file=sys.stderr)
    print(file=sys.stderr)  # Blank line for readability

    # Search all agents
    matching_sessions = search_all_agents(
        keywords,
        global_search=args.global_search,
        num_matches=args.num_matches,
        agents=args.agents,
        claude_home=args.claude_home,
        codex_home=args.codex_home,
        original_only=args.original,
        no_sub=args.no_sub,
        no_trim=args.no_trim,
        no_cont=args.no_cont,
    )

    if not matching_sessions:
        scope = "all projects" if args.global_search else "current project"
        keyword_msg = (
            f" containing all keywords: {', '.join(keywords)}" if keywords else ""
        )
        if RICH_AVAILABLE:
            console = Console()
            console.print(f"[yellow]No sessions found{keyword_msg} in {scope}[/yellow]")
        else:
            print(f"No sessions found{keyword_msg} in {scope}", file=sys.stderr)
        sys.exit(0)

    # Display interactive UI
    # ============================================================
    # UI Selection: Change DEFAULT_UI to switch the default interface
    # Options: 'tui' (Textual) or 'rich' (Rich table)
    # Alt UI (--altui) forces the Node UI runner
    # ============================================================
    DEFAULT_UI = 'rich'  # Change to 'tui' to make Textual TUI the default

    use_tui = (DEFAULT_UI == 'tui' and not args.altui) or (DEFAULT_UI == 'rich' and args.altui)

    nonlaunch_flag = {"done": False}
    action_handler = create_action_handler(shell_mode=args.shell, nonlaunch_flag=nonlaunch_flag)
    limited_sessions = matching_sessions[: args.num_matches]
    rpc_path = str(Path(__file__).parent / "action_rpc.py")

    if args.altui:
        focus_id = None
        start_action = False
        while True:
            nonlaunch_flag["done"] = False
            run_node_menu_ui(
                limited_sessions,
                keywords,
                action_handler,
                stderr_mode=args.shell,
                focus_session_id=focus_id,
                start_action=start_action,
                rpc_path=rpc_path,
                scope_line=scope_line,
                tip_line=tip_line,
            )
            if nonlaunch_flag["done"]:
                choice = prompt_post_action()
                if choice == "back":
                    focus_id = nonlaunch_flag.get("session_id")
                    start_action = True
                    continue
            break
    elif TUI_AVAILABLE and use_tui and not args.shell:
        # Use Textual TUI for interactive arrow-key navigation (default)
        run_session_tui(limited_sessions, keywords, action_handler)
    elif RICH_AVAILABLE:
        selected_session = display_interactive_ui(
            matching_sessions, keywords, stderr_mode=args.shell, num_matches=args.num_matches
        )
        if selected_session:
            # Show action menu
            action = show_action_menu(selected_session, stderr_mode=args.shell)
            if action:
                handle_action(selected_session, action, shell_mode=args.shell)
    else:
        # Fallback without rich
        print("\nMatching sessions:")
        for idx, session in enumerate(matching_sessions[: args.num_matches], 1):
            print(
                f"{idx}. [{session['agent_display']}] {session['session_id'][:16]}... | "
                f"{session['project']} | {session.get('branch', 'N/A')}"
            )


if __name__ == "__main__":
    main()
def _read_key() -> str:
    """Read a single keypress (non-blocking for Enter/Esc semantics)."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


def prompt_post_action() -> str:
    """Prompt after non-launch action: Enter exits, Esc goes back."""
    print("\n[Action complete] Press Enter to exit, or Esc to return to menu", file=sys.stderr)
    ch = _read_key()
    if ch == "\x1b":
        return "back"
    return "exit"
