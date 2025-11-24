"""Utility functions for working with Claude Code and Codex sessions."""

import os
import sys
from pathlib import Path
from typing import Optional, List


def get_claude_home(cli_arg: Optional[str] = None) -> Path:
    """
    Get Claude home directory with proper precedence.

    Precedence order:
    1. CLI argument (if provided)
    2. CLAUDE_CONFIG_DIR environment variable (if set)
    3. Default ~/.claude

    Args:
        cli_arg: Optional CLI argument value for --claude-home

    Returns:
        Path to Claude home directory
    """
    # CLI argument has highest priority
    if cli_arg:
        return Path(cli_arg).expanduser()

    # Check environment variable
    env_var = os.environ.get('CLAUDE_CONFIG_DIR')
    if env_var:
        return Path(env_var).expanduser()

    # Default fallback
    return Path.home() / ".claude"


def resolve_session_path(
    session_id_or_path: str, claude_home: Optional[str] = None
) -> Path:
    """
    Resolve a session ID or path to a full file path.

    Supports partial session ID matching. If multiple sessions match a partial
    ID, shows an error message with all matches.

    Args:
        session_id_or_path: Either a full path, full session ID, or partial
            session ID
        claude_home: Optional custom Claude home directory (defaults to
            ~/.claude or $CLAUDE_CONFIG_DIR)

    Returns:
        Resolved Path object

    Raises:
        FileNotFoundError: If session cannot be found
        ValueError: If partial ID matches multiple sessions
        SystemExit: If multiple matches found (exits with error message)
    """
    path = Path(session_id_or_path)

    # If it's already a valid path, use it
    if path.exists():
        return path

    # Otherwise, treat it as a session ID (full or partial) and try to find it
    session_id = session_id_or_path.strip()

    # Try Claude Code path first
    cwd = os.getcwd()
    base_dir = get_claude_home(claude_home)
    encoded_path = cwd.replace("/", "-")
    claude_project_dir = base_dir / "projects" / encoded_path

    claude_matches: List[Path] = []
    if claude_project_dir.exists():
        # Look for exact match first
        exact_path = claude_project_dir / f"{session_id}.jsonl"
        if exact_path.exists():
            return exact_path

        # Look for partial matches
        for jsonl_file in claude_project_dir.glob("*.jsonl"):
            if session_id in jsonl_file.stem:
                claude_matches.append(jsonl_file)

    # Try Codex path - search through sessions directory
    codex_home = Path.home() / ".codex"
    sessions_dir = codex_home / "sessions"

    codex_matches: List[Path] = []
    if sessions_dir.exists():
        for jsonl_file in sessions_dir.rglob("*.jsonl"):
            # Extract session ID from Codex filename (format: rollout-...-UUID.jsonl)
            if session_id in jsonl_file.stem:
                codex_matches.append(jsonl_file)

    # Combine all matches
    all_matches = claude_matches + codex_matches

    if len(all_matches) == 0:
        # Not found anywhere
        raise FileNotFoundError(
            f"Session '{session_id}' not found in Claude Code "
            f"({claude_project_dir}) or Codex ({sessions_dir}) directories"
        )
    elif len(all_matches) == 1:
        # Single match - perfect!
        return all_matches[0]
    else:
        # Multiple matches - show user the options
        print(
            f"Error: Multiple sessions match '{session_id}':",
            file=sys.stderr
        )
        print(file=sys.stderr)
        for i, match in enumerate(all_matches, 1):
            print(f"  {i}. {match.stem}", file=sys.stderr)
        print(file=sys.stderr)
        print(
            "Please use a more specific session ID to uniquely identify the session.",
            file=sys.stderr
        )
        sys.exit(1)


def get_current_session_id(claude_home: Optional[str] = None) -> Optional[str]:
    """
    Get the session ID of the currently active Claude Code or Codex session.

    This finds the most recently modified session file in the current
    project's session directory.

    Args:
        claude_home: Optional custom Claude home directory (default: ~/.claude)

    Returns:
        Session ID (UUID or timestamped name) if found, None otherwise
    """
    # Get current working directory
    cwd = os.getcwd()

    # Try Claude Code first
    claude_session = _get_claude_session_id(cwd, claude_home)
    if claude_session:
        return claude_session

    # Try Codex
    codex_session = _get_codex_session_id(cwd)
    if codex_session:
        return codex_session

    return None


def _get_claude_session_id(
    cwd: str, claude_home: Optional[str] = None
) -> Optional[str]:
    """Get Claude Code session ID for current directory."""
    # Convert path to Claude directory format
    base_dir = get_claude_home(claude_home)
    encoded_path = cwd.replace("/", "-")
    claude_project_dir = base_dir / "projects" / encoded_path

    if not claude_project_dir.exists():
        return None

    # Find most recently modified .jsonl file
    session_files = list(claude_project_dir.glob("*.jsonl"))
    if not session_files:
        return None

    most_recent = max(session_files, key=lambda p: p.stat().st_mtime)
    return most_recent.stem  # Filename without .jsonl extension


def _get_codex_session_id(cwd: str) -> Optional[str]:
    """Get Codex session ID for current directory."""
    codex_dir = Path.home() / ".codex" / "sessions"

    if not codex_dir.exists():
        return None

    # Find most recently modified .jsonl file
    # Codex sessions are organized by date: 2025/11/14/rollout-...jsonl
    session_files = list(codex_dir.rglob("*.jsonl"))
    if not session_files:
        return None

    # Filter to sessions in current directory
    # Codex sessions don't have directory-specific organization,
    # so we just return the most recent one
    most_recent = max(session_files, key=lambda p: p.stat().st_mtime)
    return most_recent.stem  # Filename without .jsonl extension


def execute_continue_action(
    session_file_path: str,
    current_agent: str,
    claude_home: Optional[str] = None,
    codex_home: Optional[str] = None
) -> None:
    """
    Execute continue action with agent selection dialog.

    Provides interactive menu for choosing which agent to use for
    continuation (same-agent or cross-agent), prompts for custom
    summarization instructions, and routes to the appropriate
    continue command.

    Args:
        session_file_path: Path to the session file to continue
        current_agent: Agent type of the session ('claude' or 'codex')
        claude_home: Optional custom Claude home directory
        codex_home: Optional custom Codex home directory
    """
    print("\n🔄 Starting continuation in fresh session...")

    # Ask which agent to use for continuation
    print(f"\nCurrent session is from: {current_agent.upper()}")
    print("Which agent should continue the work?")
    print(f"1. {current_agent.upper()} (default - same agent)")
    other_agent = "CODEX" if current_agent == "claude" else "CLAUDE"
    print(f"2. {other_agent} (cross-agent)")
    print()

    try:
        choice = input(
            f"Enter choice [1-2] (or Enter for {current_agent.upper()}): "
        ).strip()
        if not choice or choice == "1":
            continue_agent = current_agent
        elif choice == "2":
            continue_agent = "codex" if current_agent == "claude" else "claude"
        else:
            print("Invalid choice, using default.")
            continue_agent = current_agent
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return

    print(f"\nℹ️  Continuing with {continue_agent.upper()}")

    # Prompt for custom instructions
    print("\nEnter custom summarization instructions (or press Enter to skip):")
    custom_prompt = input("> ").strip() or None

    if continue_agent == "claude":
        from claude_code_tools.claude_continue import claude_continue
        claude_continue(
            session_file_path,
            claude_home=claude_home,
            verbose=False,
            custom_prompt=custom_prompt
        )
    else:
        from claude_code_tools.codex_continue import codex_continue
        codex_continue(
            session_file_path,
            codex_home=codex_home,
            verbose=False,
            custom_prompt=custom_prompt
        )
