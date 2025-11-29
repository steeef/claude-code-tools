"""Export all sessions with YAML front matter for indexing."""

import json
from pathlib import Path
from typing import Optional

from claude_code_tools.export_session import export_with_yaml_frontmatter
from claude_code_tools.session_utils import (
    extract_cwd_from_session,
    get_claude_home,
    get_codex_home,
    is_valid_session,
)


def is_sidechain_session(session_file: Path) -> bool:
    """
    Check if a session is a sidechain (sub-agent) session.

    Quickly scans the first 30 lines for isSidechain: true.

    Args:
        session_file: Path to session JSONL file

    Returns:
        True if session has isSidechain=True, False otherwise
    """
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 30:  # Only check first 30 lines
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("isSidechain") is True:
                        return True
                except json.JSONDecodeError:
                    continue
    except (OSError, IOError):
        pass
    return False


def is_valid_codex_session(session_file: Path) -> bool:
    """
    Check if a Codex session file has actual conversation messages.

    Codex sessions use a different format than Claude:
    - Messages have type="response_item" with payload.type="message"

    Args:
        session_file: Path to Codex session JSONL file

    Returns:
        True if session has at least one conversation message
    """
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    # Codex conversation messages
                    if data.get("type") == "response_item":
                        payload = data.get("payload", {})
                        if payload.get("type") == "message":
                            return True
                except json.JSONDecodeError:
                    continue
    except (OSError, IOError):
        pass
    return False


def should_export_session(session_file: Path, agent: str) -> bool:
    """
    Check if a session should be exported to the search index.

    A session should be exported if:
    - It is resumable (has at least one user/assistant/tool_result/tool_use message), OR
    - It is a sidechain (sub-agent) session

    This filters out sessions that only contain non-resumable metadata
    (like file-history-snapshot, queue-operation).

    Args:
        session_file: Path to session JSONL file
        agent: Agent type ('claude' or 'codex')

    Returns:
        True if session should be exported, False otherwise
    """
    # Check if it's a resumable session based on agent type
    if agent == "claude":
        if is_valid_session(session_file):
            return True
    elif agent == "codex":
        if is_valid_codex_session(session_file):
            return True

    # Even if not resumable, include sub-agent sessions
    if is_sidechain_session(session_file):
        return True

    return False


def extract_export_dir_from_session(session_file: Path, agent: str) -> Optional[Path]:
    """
    Get the export directory for a session file.

    Extracts the cwd (working directory) from the session and returns the
    export path: {cwd}/exported-sessions/{agent}/

    This abstracts the export location decision so it can be changed in the
    future (e.g., to a centralized location) without modifying callers.

    Args:
        session_file: Path to session JSONL file
        agent: Agent type ('claude' or 'codex')

    Returns:
        Path to export directory, or None if cwd cannot be extracted
    """
    cwd = extract_cwd_from_session(session_file)
    if not cwd:
        return None
    return Path(cwd) / "exported-sessions" / agent


def find_all_claude_sessions(claude_home: Path) -> list[Path]:
    """
    Find all Claude Code session files.

    Args:
        claude_home: Path to Claude home directory

    Returns:
        List of session file paths
    """
    sessions = []
    projects_dir = claude_home / "projects"

    if not projects_dir.exists():
        return sessions

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for session_file in project_dir.glob("*.jsonl"):
            sessions.append(session_file)

    return sessions


def find_all_codex_sessions(codex_home: Path) -> list[Path]:
    """
    Find all Codex CLI session files.

    Args:
        codex_home: Path to Codex home directory

    Returns:
        List of session file paths
    """
    sessions = []
    sessions_dir = codex_home / "sessions"

    if not sessions_dir.exists():
        return sessions

    # Codex sessions are organized: sessions/YYYY/MM/DD/*.jsonl
    for session_file in sessions_dir.rglob("*.jsonl"):
        sessions.append(session_file)

    return sessions


def needs_export(session_file: Path, export_file: Path) -> bool:
    """
    Check if a session needs to be (re-)exported.

    Returns True if:
    - Export file doesn't exist
    - Session file is newer than export file

    Args:
        session_file: Path to session JSONL
        export_file: Path to export .txt

    Returns:
        True if export is needed
    """
    if not export_file.exists():
        return True

    session_mtime = session_file.stat().st_mtime
    export_mtime = export_file.stat().st_mtime

    return session_mtime > export_mtime


def collect_sessions_to_export(
    claude_home: Optional[Path] = None,
    codex_home: Optional[Path] = None,
) -> list[tuple[Path, str]]:
    """
    Collect all sessions that should be exported.

    Returns:
        List of (session_file, agent) tuples
    """
    if claude_home is None:
        claude_home = get_claude_home()
    if codex_home is None:
        codex_home = get_codex_home()

    sessions = []

    # Claude sessions
    for session_file in find_all_claude_sessions(claude_home):
        if should_export_session(session_file, agent="claude"):
            sessions.append((session_file, "claude"))

    # Codex sessions
    for session_file in find_all_codex_sessions(codex_home):
        if should_export_session(session_file, agent="codex"):
            sessions.append((session_file, "codex"))

    return sessions


def export_single_session(
    session_file: Path,
    agent: str,
    force: bool = False,
) -> dict:
    """
    Export a single session file.

    Args:
        session_file: Path to session JSONL file
        agent: Agent type ('claude' or 'codex')
        force: If True, re-export even if up-to-date

    Returns:
        Dict with result: {status, export_file, error}
        status: 'exported', 'skipped', 'failed'
    """
    result: dict = {"status": "failed", "export_file": None, "error": None}

    # Get per-project export directory
    export_dir = extract_export_dir_from_session(session_file, agent=agent)
    if export_dir is None:
        result["error"] = "no cwd in session"
        return result

    export_dir.mkdir(parents=True, exist_ok=True)
    export_file = export_dir / f"{session_file.stem}.txt"
    result["export_file"] = export_file

    if not force and not needs_export(session_file, export_file):
        result["status"] = "skipped"
        return result

    try:
        export_with_yaml_frontmatter(session_file, export_file, agent=agent)
        result["status"] = "exported"
    except Exception as e:
        result["error"] = str(e)

    return result


def export_all_sessions(
    claude_home: Optional[Path] = None,
    codex_home: Optional[Path] = None,
    force: bool = False,
    verbose: bool = False,
) -> dict:
    """
    Export all Claude and Codex sessions with YAML front matter.

    Each session is exported to its own project directory:
    {project_cwd}/exported-sessions/{agent}/{session_id}.txt

    Args:
        claude_home: Claude home directory (default: ~/.claude)
        codex_home: Codex home directory (default: ~/.codex)
        force: If True, re-export all sessions even if up-to-date
        verbose: If True, print progress

    Returns:
        Dict with counts and file lists:
        {
            exported: int,
            skipped: int,
            failed: int,
            exported_files: list[Path],
            failures: list[dict]  # Detailed failure info
        }
    """
    stats: dict = {
        "exported": 0,
        "skipped": 0,
        "failed": 0,
        "exported_files": [],
        "failures": [],
    }

    sessions = collect_sessions_to_export(claude_home, codex_home)

    for session_file, agent in sessions:
        result = export_single_session(session_file, agent, force)

        if result["status"] == "exported":
            stats["exported"] += 1
            stats["exported_files"].append(result["export_file"])
            if verbose:
                print(f"  Exported: {session_file.name}")
        elif result["status"] == "skipped":
            stats["skipped"] += 1
            if result["export_file"]:
                stats["exported_files"].append(result["export_file"])
            if verbose:
                print(f"  Skipped (up-to-date): {session_file.name}")
        else:  # failed
            stats["failed"] += 1
            stats["failures"].append({
                "session": str(session_file),
                "agent": agent,
                "error": result["error"],
            })
            if verbose:
                print(f"  Failed: {session_file.name} - {result['error']}")

    return stats
