"""Utility functions for working with Claude Code and Codex sessions."""

import json
import os
import sys
from pathlib import Path
from typing import Optional, List, Tuple


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


def get_codex_home(cli_arg: Optional[str] = None) -> Path:
    """
    Get Codex home directory.

    Args:
        cli_arg: Optional CLI argument value for --codex-home

    Returns:
        Path to Codex home directory (default: ~/.codex)
    """
    if cli_arg:
        return Path(cli_arg).expanduser()
    return Path.home() / ".codex"


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


def detect_agent_from_path(file_path: Path) -> Optional[str]:
    """
    Auto-detect agent type from file path.

    Args:
        file_path: Path to session file

    Returns:
        'claude', 'codex', or None if cannot detect
    """
    path_str = str(file_path.absolute())

    if "/.claude/" in path_str or path_str.startswith(
        str(Path.home() / ".claude")
    ):
        return "claude"
    elif "/.codex/" in path_str or path_str.startswith(
        str(Path.home() / ".codex")
    ):
        return "codex"

    return None


def is_valid_session(filepath: Path) -> bool:
    """
    Check if a session file is a valid Claude Code session (WHITELIST approach).

    A session is valid if it contains at least ONE line with a resumable message type
    (user, assistant, tool_result, tool_use). Sessions containing ONLY metadata types
    (file-history-snapshot, queue-operation) are invalid.

    Real Claude sessions often start with file-history-snapshot lines (with null sessionId)
    followed by actual conversation messages. We must scan ALL lines to determine validity.

    Args:
        filepath: Path to session JSONL file.

    Returns:
        True if session contains at least one resumable message, False otherwise.
    """
    if not filepath.exists():
        return False

    # Whitelist of resumable message types
    valid_types = ["user", "assistant", "tool_result", "tool_use"]

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            has_any_content = False

            for line in f:
                line = line.strip()
                if not line:
                    continue

                has_any_content = True

                try:
                    data = json.loads(line)
                    entry_type = data.get("type", "")
                    session_id = data.get("sessionId")

                    # Found a valid resumable message type with non-null sessionId
                    if entry_type in valid_types and session_id is not None:
                        return True

                except json.JSONDecodeError:
                    # Skip malformed JSON lines, continue checking other lines
                    continue

            # If we scanned entire file and found no valid message types
            # (only metadata or empty), session is invalid
            return False if has_any_content else False  # Empty file is invalid

    except (OSError, IOError):
        return False  # File read errors indicate invalid file


def is_malformed_session(filepath: Path) -> bool:
    """
    Deprecated: Use is_valid_session() instead.
    Kept for backward compatibility - returns inverse of is_valid_session().

    Returns:
        True if session is malformed/invalid, False if valid.
    """
    return not is_valid_session(filepath)


def extract_cwd_from_session(session_file: Path) -> Optional[str]:
    """
    Extract the working directory (cwd) from a Claude session file.

    Real Claude sessions often have file-history-snapshot lines with null cwd values
    at the start, followed by actual messages with valid cwd. We check first 10 lines
    and skip null values.

    Args:
        session_file: Path to the session JSONL file

    Returns:
        The cwd string if found, None otherwise
    """
    try:
        with open(session_file, 'r', encoding='utf-8') as f:
            # Check first 10 lines for non-null cwd field
            for i, line in enumerate(f):
                if i >= 10:  # Check first 10 lines (increased from 5)
                    break
                try:
                    data = json.loads(line.strip())
                    if "cwd" in data and data["cwd"] is not None:
                        return data["cwd"]
                except (json.JSONDecodeError, KeyError):
                    continue
    except (OSError, IOError):
        pass

    return None


def extract_git_branch_claude(session_file: Path) -> Optional[str]:
    """Extract git branch from Claude session file."""
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "file-history-snapshot":
                        git_info = entry.get("metadata", {}).get("git", {})
                        return git_info.get("branch")
                except json.JSONDecodeError:
                    continue
    except (OSError, IOError):
        pass
    return None


def extract_session_metadata_codex(session_file: Path) -> Optional[dict]:
    """Extract metadata from Codex session file."""
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "session_meta":
                        payload = entry.get("payload", {})
                        return {
                            "cwd": payload.get("cwd"),
                            "branch": payload.get("branch"),
                        }
                except json.JSONDecodeError:
                    continue
    except (OSError, IOError):
        pass
    return None


def find_session_file(
    session_id: str,
    claude_home: Optional[str] = None,
    codex_home: Optional[str] = None,
) -> Optional[Tuple[str, Path, str, Optional[str]]]:
    """
    Search for session file by ID in both Claude and Codex homes.

    Args:
        session_id: Session identifier
        claude_home: Optional custom Claude home directory
        codex_home: Optional custom Codex home directory

    Returns:
        Tuple of (agent, file_path, project_path, git_branch) or None
        Note: project_path is the full working directory path, not just the name
    """
    # Try Claude first
    claude_base = get_claude_home(claude_home)
    if claude_base.exists():
        projects_dir = claude_base / "projects"
        if projects_dir.exists():
            for project_dir in projects_dir.iterdir():
                if project_dir.is_dir():
                    # Support partial session ID matching
                    for session_file in project_dir.glob(f"*{session_id}*.jsonl"):
                        # Skip malformed/invalid sessions
                        if is_malformed_session(session_file):
                            continue
                        # Extract actual cwd from session file
                        actual_cwd = extract_cwd_from_session(session_file)
                        if not actual_cwd:
                            # Skip sessions without cwd
                            continue
                        # Try to get git branch from session file
                        git_branch = extract_git_branch_claude(session_file)
                        return ("claude", session_file, actual_cwd, git_branch)

    # Try Codex next
    codex_base = get_codex_home(codex_home)
    if codex_base.exists():
        sessions_dir = codex_base / "sessions"
        if sessions_dir.exists():
            # Search through date directories
            for year_dir in sessions_dir.iterdir():
                if not year_dir.is_dir():
                    continue
                for month_dir in year_dir.iterdir():
                    if not month_dir.is_dir():
                        continue
                    for day_dir in month_dir.iterdir():
                        if not day_dir.is_dir():
                            continue
                        # Look for session files matching the ID
                        for session_file in day_dir.glob(f"*{session_id}*.jsonl"):
                            # Extract metadata from file
                            metadata = extract_session_metadata_codex(session_file)
                            if metadata:
                                project_path = metadata.get("cwd", "")
                                git_branch = metadata.get("branch")
                                return (
                                    "codex",
                                    session_file,
                                    project_path,
                                    git_branch,
                                )

    return None


def format_session_id_display(
    session_id: str,
    is_trimmed: bool = False,
    is_continued: bool = False,
    is_sidechain: bool = False,
    truncate_length: int = 8,
) -> str:
    """
    Format session ID with annotations for display in find commands.

    Provides consistent session ID formatting across all find commands
    (find, find-claude, find-codex) with standard annotations.

    Args:
        session_id: Full session ID string
        is_trimmed: Whether session is trimmed (adds "(t)")
        is_continued: Whether session is continued (adds "(c)")
        is_sidechain: Whether session is a sub-agent (adds "(sub)")
        truncate_length: Number of characters to show before "..." (default 8)

    Returns:
        Formatted string like "abc123... (t) (sub)"

    Examples:
        >>> format_session_id_display("abc123-def456", is_trimmed=True)
        'abc123... (t)'
        >>> format_session_id_display("abc123-def456", is_sidechain=True, truncate_length=16)
        'abc123-def456... (sub)'
    """
    display = session_id[:truncate_length] + "..."

    if is_trimmed:
        display += " (t)"
    if is_continued:
        display += " (c)"
    if is_sidechain:
        display += " (sub)"

    return display
