"""Export all sessions with YAML front matter for indexing."""

from pathlib import Path
from typing import Optional

from claude_code_tools.export_session import export_with_yaml_frontmatter
from claude_code_tools.session_utils import get_claude_home, get_codex_home


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


def export_all_sessions(
    output_dir: Path,
    claude_home: Optional[Path] = None,
    codex_home: Optional[Path] = None,
    force: bool = False,
    verbose: bool = False,
) -> dict[str, int]:
    """
    Export all Claude and Codex sessions with YAML front matter.

    Args:
        output_dir: Base directory for exports (will contain claude/ and codex/ subdirs)
        claude_home: Claude home directory (default: ~/.claude)
        codex_home: Codex home directory (default: ~/.codex)
        force: If True, re-export all sessions even if up-to-date
        verbose: If True, print progress

    Returns:
        Stats dict with counts: {exported, skipped, failed}
    """
    stats = {"exported": 0, "skipped": 0, "failed": 0}

    # Resolve home directories
    if claude_home is None:
        claude_home = get_claude_home()
    if codex_home is None:
        codex_home = get_codex_home()

    # Ensure output directories exist
    claude_output = output_dir / "claude"
    codex_output = output_dir / "codex"
    claude_output.mkdir(parents=True, exist_ok=True)
    codex_output.mkdir(parents=True, exist_ok=True)

    # Export Claude sessions
    claude_sessions = find_all_claude_sessions(claude_home)
    for session_file in claude_sessions:
        export_file = claude_output / f"{session_file.stem}.txt"

        if not force and not needs_export(session_file, export_file):
            stats["skipped"] += 1
            if verbose:
                print(f"  Skipped (up-to-date): {session_file.name}")
            continue

        try:
            export_with_yaml_frontmatter(session_file, export_file, agent="claude")
            stats["exported"] += 1
            if verbose:
                print(f"  Exported: {session_file.name}")
        except Exception as e:
            stats["failed"] += 1
            if verbose:
                print(f"  Failed: {session_file.name} - {e}")

    # Export Codex sessions
    codex_sessions = find_all_codex_sessions(codex_home)
    for session_file in codex_sessions:
        export_file = codex_output / f"{session_file.stem}.txt"

        if not force and not needs_export(session_file, export_file):
            stats["skipped"] += 1
            if verbose:
                print(f"  Skipped (up-to-date): {session_file.name}")
            continue

        try:
            export_with_yaml_frontmatter(session_file, export_file, agent="codex")
            stats["exported"] += 1
            if verbose:
                print(f"  Exported: {session_file.name}")
        except Exception as e:
            stats["failed"] += 1
            if verbose:
                print(f"  Failed: {session_file.name} - {e}")

    return stats
