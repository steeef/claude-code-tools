"""Utility functions for working with Claude Code and Codex sessions."""

import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple


def parse_flexible_timestamp(ts_str: str, is_upper_bound: bool = False) -> float:
    """
    Parse a flexible timestamp string into a Unix timestamp.

    Supports date formats:
        20251120           - YYYYMMDD
        2025-11-20         - YYYY-MM-DD (ISO)
        11/20/25           - MM/DD/YY
        11/20/2025         - MM/DD/YYYY

    Supports optional time suffix (T or space separator):
        ...T16:45:23 or ... 16:45:23  - full time
        ...T16:45 or ... 16:45        - without seconds
        ...T16 or ... 16              - hour only

    Args:
        ts_str: Timestamp string in one of the supported formats
        is_upper_bound: If True (for --before), fill missing parts with max values
                       (23:59:59). If False (for --after), fill with min values
                       (00:00:00).

    Returns:
        Unix timestamp (float)

    Raises:
        ValueError: If the timestamp format is invalid
    """
    ts_str = ts_str.strip()

    # Split date and time parts (separator: T or space)
    time_part = None
    if 'T' in ts_str:
        date_str, time_part = ts_str.split('T', 1)
    elif ' ' in ts_str:
        date_str, time_part = ts_str.split(' ', 1)
    else:
        date_str = ts_str

    # Parse date part - try multiple formats
    year, month, day = None, None, None

    # YYYYMMDD
    if re.match(r'^\d{8}$', date_str):
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])
    # YYYY-MM-DD (ISO)
    elif re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', date_str):
        parts = date_str.split('-')
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
    # MM/DD/YY or MM/DD/YYYY
    elif re.match(r'^\d{1,2}/\d{1,2}/\d{2,4}$', date_str):
        parts = date_str.split('/')
        month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
        if year < 100:
            year += 2000  # 25 -> 2025
    else:
        raise ValueError(
            f"Invalid date format: {date_str}. "
            "Expected: YYYYMMDD, YYYY-MM-DD, MM/DD/YY, or MM/DD/YYYY"
        )

    # Parse time part if present
    hour, minute, second = None, None, None
    if time_part:
        time_match = re.match(r'^(\d{1,2})(?::(\d{2})(?::(\d{2}))?)?$', time_part)
        if not time_match:
            raise ValueError(
                f"Invalid time format: {time_part}. "
                "Expected: HH, HH:MM, or HH:MM:SS"
            )
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else None
        second = int(time_match.group(3)) if time_match.group(3) else None

    # Fill missing time components based on bound type
    if hour is None:
        hour = 23 if is_upper_bound else 0
        minute = 59 if is_upper_bound else 0
        second = 59 if is_upper_bound else 0
    else:
        if minute is None:
            minute = 59 if is_upper_bound else 0
            second = 59 if is_upper_bound else 0
        elif second is None:
            second = 59 if is_upper_bound else 0

    dt = datetime(year, month, day, hour, minute, second)
    return dt.timestamp()


def filter_sessions_by_time(
    sessions: list,
    before: Optional[str] = None,
    after: Optional[str] = None,
    time_key: str = "mod_time",
    time_index: Optional[int] = None,
) -> list:
    """
    Filter sessions by time bounds.

    Args:
        sessions: List of sessions (dicts or tuples)
        before: Upper bound timestamp string (inclusive)
        after: Lower bound timestamp string (inclusive)
        time_key: Key to use for dict sessions (default: "mod_time")
        time_index: Index to use for tuple sessions (if None, uses time_key for dicts)

    Returns:
        Filtered list of sessions
    """
    if not before and not after:
        return sessions

    before_ts = parse_flexible_timestamp(before, is_upper_bound=True) if before else None
    after_ts = parse_flexible_timestamp(after, is_upper_bound=False) if after else None

    def get_time(session):
        if time_index is not None:
            return session[time_index]
        return session.get(time_key, 0)

    result = []
    for s in sessions:
        t = get_time(s)
        if before_ts is not None and t > before_ts:
            continue
        if after_ts is not None and t < after_ts:
            continue
        result.append(s)

    return result


def is_agent_available(agent: str) -> bool:
    """
    Check if a coding agent is available on this system.

    Checks two conditions (either one is sufficient):
    1. The agent command exists in PATH (e.g., 'claude' or 'codex')
    2. The agent config directory exists (e.g., ~/.claude or ~/.codex)

    Args:
        agent: Agent name ('claude' or 'codex')

    Returns:
        True if the agent is available, False otherwise
    """
    agent = agent.lower()

    # Check if command exists in PATH
    command = "claude" if agent == "claude" else "codex"
    if shutil.which(command):
        return True

    # Check if config directory exists
    config_dir = Path.home() / f".{agent}"
    if config_dir.exists() and config_dir.is_dir():
        return True

    return False


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


def encode_claude_project_path(project_path: str) -> str:
    """
    Encode a project path to Claude's directory naming format.

    Claude Code replaces certain characters when creating project directories.
    This function replicates that encoding to ensure path reconstruction matches.

    Known character replacements:
    - '/' → '-' (path separators)
    - '_' → '-' (underscores, common in temp directories)
    - '.' → '-' (dots, e.g., .claude-trace directories)

    Args:
        project_path: Absolute path to project directory
            (e.g., /Users/foo/Git/my_project)

    Returns:
        Encoded path suitable for Claude's projects directory
            (e.g., -Users-foo-Git-my-project)
    """
    return project_path.replace("/", "-").replace("_", "-").replace(".", "-")


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

    # Search ALL Claude project directories globally
    base_dir = get_claude_home(claude_home)
    projects_dir = base_dir / "projects"

    claude_matches: List[Path] = []
    if projects_dir.exists():
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            # Look for exact match first (fast path)
            exact_path = project_dir / f"{session_id}.jsonl"
            if exact_path.exists():
                return exact_path
            # Collect partial matches
            for jsonl_file in project_dir.glob("*.jsonl"):
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
            f"({projects_dir}) or Codex ({sessions_dir}) directories"
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
    encoded_path = encode_claude_project_path(cwd)
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


def display_lineage(
    session_file: Path,
    agent_type: str,
    claude_home: Optional[str] = None,
    codex_home: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[List, Path]:
    """
    Export session and display continuation lineage.

    This function:
    1. Exports the current session to a text file
    2. Traces the continuation lineage (all parent sessions)
    3. Displays the lineage chain to the user
    4. Returns the lineage and exported files for use by continue functions

    Args:
        session_file: Path to the session file to analyze
        agent_type: 'claude' or 'codex'
        claude_home: Optional custom Claude home directory
        codex_home: Optional custom Codex home directory
        verbose: If True, show detailed progress

    Returns:
        Tuple of (lineage_nodes, current_session_export_path)
        where lineage_nodes is a list of LineageNode objects
    """
    from claude_code_tools.session_lineage import get_continuation_lineage

    # Step 1: Export the current session
    print("Step 1: Exporting session to text file...")

    if agent_type == "claude":
        from claude_code_tools.export_claude_session import (
            export_session_programmatic,
        )
        chat_log = export_session_programmatic(
            str(session_file),
            claude_home=claude_home,
            verbose=verbose,
        )
    else:
        from claude_code_tools.export_codex_session import (
            export_session_programmatic,
        )
        chat_log = export_session_programmatic(
            str(session_file),
            codex_home=codex_home,
            verbose=verbose,
        )

    print(f"✅ Exported chat log to: {chat_log}")
    print()

    # Step 2: Get and display continuation lineage
    print("Step 2: Tracing continuation lineage...")

    try:
        lineage = get_continuation_lineage(session_file, export_missing=True)

        if lineage:
            print(f"✅ Found {len(lineage)} session(s) in continuation chain:")
            for node in lineage:
                derivation_label = (
                    f"({node.derivation_type})" if node.derivation_type else ""
                )
                print(f"   - {node.session_file.name} {derivation_label}")
                if node.exported_file:
                    print(f"     Export: {node.exported_file}")
            print()
        else:
            print("✅ No previous sessions in continuation chain (this is the original)")
            print()

    except Exception as e:
        print(f"⚠️  Warning: Could not trace lineage: {e}", file=sys.stderr)
        lineage = []

    return lineage, chat_log


def continue_with_options(
    session_file_path: str,
    current_agent: str,
    claude_home: Optional[str] = None,
    codex_home: Optional[str] = None,
    preset_agent: Optional[str] = None,
    preset_prompt: Optional[str] = None,
) -> None:
    """
    Unified continue flow with proper timing.

    This function provides the complete continue experience:
    1. Export current session
    2. Display lineage (so user sees full history)
    3. Prompt for agent choice (unless preset_agent provided)
    4. Prompt for custom instructions (unless preset_prompt provided)
    5. Execute continuation with chosen options

    Args:
        session_file_path: Path to the session file to continue
        current_agent: Agent type of the session ('claude' or 'codex')
        claude_home: Optional custom Claude home directory
        codex_home: Optional custom Codex home directory
        preset_agent: If provided, skip agent choice prompt and use this agent
        preset_prompt: If provided, skip custom prompt and use this
    """
    session_file = Path(session_file_path)

    print("\n🔄 Starting continuation in fresh session...")
    print()

    # Step 1-2: Export and display lineage FIRST
    # This allows user to make informed decisions
    lineage, chat_log = display_lineage(
        session_file,
        current_agent,
        claude_home=claude_home,
        codex_home=codex_home,
    )

    # Collect all exported files in chronological order
    all_exported_files = [
        node.exported_file for node in lineage if node.exported_file
    ]
    all_exported_files.append(chat_log)

    # Step 3: Prompt for agent choice (unless preset or other agent unavailable)
    other_agent_name = "codex" if current_agent == "claude" else "claude"

    if preset_agent:
        continue_agent = preset_agent.lower()
        print(f"ℹ️  Using specified agent: {continue_agent.upper()}")
    elif not is_agent_available(other_agent_name):
        # Other agent not available, use current agent without prompting
        continue_agent = current_agent
        print(f"ℹ️  Continuing with {current_agent.upper()}")
    else:
        # Both agents available, offer choice
        print(f"Current session is from: {current_agent.upper()}")
        print("Which agent should continue the work?")
        print(f"1. {current_agent.upper()} (default - same agent)")
        print(f"2. {other_agent_name.upper()} (cross-agent)")
        print()

        try:
            choice = input(
                f"Enter choice [1-2] (or Enter for {current_agent.upper()}): "
            ).strip()
            if not choice or choice == "1":
                continue_agent = current_agent
            elif choice == "2":
                continue_agent = other_agent_name
            else:
                print("Invalid choice, using default.")
                continue_agent = current_agent
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return

    print(f"\nℹ️  Continuing with {continue_agent.upper()}")

    # Step 4: Prompt for custom instructions (unless preset)
    if preset_prompt is not None:
        custom_prompt = preset_prompt if preset_prompt else None
        if custom_prompt:
            print(f"ℹ️  Using custom prompt: {custom_prompt[:50]}...")
    else:
        print("\nEnter custom summarization instructions (or press Enter to skip):")
        try:
            custom_prompt = input("> ").strip() or None
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return

    # Step 5: Execute continuation with precomputed data
    if continue_agent == "claude":
        from claude_code_tools.claude_continue import claude_continue
        claude_continue(
            str(session_file),
            claude_home=claude_home,
            verbose=False,
            custom_prompt=custom_prompt,
            precomputed_exports=all_exported_files,
        )
    else:
        from claude_code_tools.codex_continue import codex_continue
        codex_continue(
            str(session_file),
            codex_home=codex_home,
            verbose=False,
            custom_prompt=custom_prompt,
            precomputed_exports=all_exported_files,
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
    Extract the working directory (cwd) from a session file.

    Supports both Claude and Codex session formats:
    - Claude: top-level "cwd" field
    - Codex: "payload.cwd" field

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
                    # Claude format: top-level cwd
                    if "cwd" in data and data["cwd"] is not None:
                        return data["cwd"]
                    # Codex format: payload.cwd
                    if "payload" in data and isinstance(data["payload"], dict):
                        payload_cwd = data["payload"].get("cwd")
                        if payload_cwd is not None:
                            return payload_cwd
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
                        git_info = payload.get("git", {})
                        return {
                            "cwd": payload.get("cwd"),
                            "branch": git_info.get("branch"),
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


def default_export_path(
    session_file: Path,
    agent: str,
    base_dir: Optional[Path] = None,
) -> Path:
    """
    Generate default export path for a session.

    Path format: {base_dir}/exported-sessions/{agent}/{session_filename}.txt

    Args:
        session_file: Path to the session file
        agent: Agent type ('claude' or 'codex')
        base_dir: Base directory (defaults to session's project dir, then cwd)

    Returns:
        Path to the export file
    """
    if base_dir is None:
        # Infer base_dir from session file metadata
        if agent == "codex":
            metadata = extract_session_metadata_codex(session_file)
            if metadata and metadata.get("cwd"):
                base_dir = Path(metadata["cwd"])
        else:  # claude
            cwd = extract_cwd_from_session(session_file)
            if cwd:
                base_dir = Path(cwd)

        # Fall back to cwd if inference fails
        if base_dir is None:
            base_dir = Path.cwd()

    agent_dir = "codex" if agent == "codex" else "claude"
    filename = session_file.stem + ".txt"

    return base_dir / "exported-sessions" / agent_dir / filename
