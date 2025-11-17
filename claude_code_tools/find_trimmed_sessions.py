#!/usr/bin/env python3
"""
Find all trimmed sessions derived from an original session.

Searches session directories for files with trim_metadata that link back
to the specified session file, either directly or through a chain of parents.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Set, Optional

from claude_code_tools.session_utils import get_claude_home


def resolve_session_path(session_id_or_path: str, claude_home: Optional[str] = None) -> Path:
    """
    Resolve a session ID or path to a full file path.

    Args:
        session_id_or_path: Either a full path or a session UUID
        claude_home: Optional custom Claude home directory (defaults to ~/.claude)

    Returns:
        Resolved Path object

    Raises:
        FileNotFoundError: If session cannot be found
    """
    path = Path(session_id_or_path)

    # If it's already a valid path, use it
    if path.exists():
        return path

    # Otherwise, treat it as a session ID and try to find it
    session_id = session_id_or_path.strip()

    # Try Claude Code path first
    cwd = os.getcwd()
    base_dir = get_claude_home(claude_home)
    encoded_path = cwd.replace("/", "-")
    claude_project_dir = base_dir / "projects" / encoded_path
    claude_path = claude_project_dir / f"{session_id}.jsonl"

    if claude_path.exists():
        return claude_path

    # Try Codex path - search through sessions directory
    codex_home = Path.home() / ".codex"
    sessions_dir = codex_home / "sessions"

    if sessions_dir.exists():
        # Search for files containing the session ID in the filename
        for jsonl_file in sessions_dir.rglob("*.jsonl"):
            if session_id in jsonl_file.name:
                return jsonl_file

    # Not found anywhere
    raise FileNotFoundError(
        f"Session '{session_id}' not found in Claude Code "
        f"({claude_path}) or Codex ({sessions_dir}) directories"
    )


def find_direct_children(
    parent_file: Path, search_dirs: List[Path]
) -> List[Path]:
    """
    Find direct children of a session file.

    Args:
        parent_file: Path to parent session file.
        search_dirs: Directories to search for trimmed sessions.

    Returns:
        List of paths to direct child sessions.
    """
    parent_abs = str(parent_file.absolute())
    children = []

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue

        for jsonl_file in search_dir.rglob("*.jsonl"):
            try:
                with open(jsonl_file) as f:
                    first_line = f.readline().strip()

                data = json.loads(first_line)
                if "trim_metadata" in data:
                    trim_meta = data["trim_metadata"]
                    if trim_meta.get("parent_file") == parent_abs:
                        children.append(jsonl_file)
            except (json.JSONDecodeError, IOError):
                continue

    return children


def find_all_descendants(
    session_file: Path, search_dirs: List[Path]
) -> Dict[Path, List[Path]]:
    """
    Find all descendant sessions recursively.

    Args:
        session_file: Path to original session file.
        search_dirs: Directories to search for trimmed sessions.

    Returns:
        Dict mapping each session to its direct children.
    """
    lineage = {}
    to_process = [session_file]
    processed: Set[Path] = set()

    while to_process:
        current = to_process.pop(0)
        if current in processed:
            continue

        processed.add(current)
        children = find_direct_children(current, search_dirs)
        lineage[current] = children

        # Add children to processing queue
        to_process.extend(children)

    return lineage


def print_tree(
    lineage: Dict[Path, List[Path]], root: Path, indent: str = ""
) -> None:
    """
    Print lineage tree recursively.

    Args:
        lineage: Dict mapping parents to children.
        root: Current root node.
        indent: Current indentation level.
    """
    children = lineage.get(root, [])

    if not children:
        return

    for i, child in enumerate(sorted(children)):
        is_last = i == len(children) - 1
        connector = "└─> " if is_last else "├─> "
        print(f"{indent}{connector}{child}")

        # Recursively print children
        child_indent = indent + ("    " if is_last else "│   ")
        print_tree(lineage, child, child_indent)


def get_search_dirs(custom_dir: Path = None, claude_home: Optional[str] = None) -> List[Path]:
    """
    Get list of directories to search for sessions.

    Args:
        custom_dir: Optional custom directory to search.
        claude_home: Optional custom Claude home directory.

    Returns:
        List of directories to search.
    """
    if custom_dir:
        return [custom_dir]

    base_dir = get_claude_home(claude_home)
    codex_home = Path.home() / ".codex"

    return [
        base_dir / "projects",  # Search all Claude projects
        codex_home / "sessions",
    ]


def main() -> None:
    """Parse arguments and find trimmed sessions."""
    parser = argparse.ArgumentParser(
        description="Find all trimmed sessions derived from an original.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Find all trimmed sessions from an original
  %(prog)s ~/.claude/sessions/abc123.jsonl

  # Show as a tree
  %(prog)s ~/.codex/sessions/2024/10/24/rollout-xyz.jsonl --tree

  # Search custom directory
  %(prog)s /tmp/session.jsonl --search-dir /tmp
        """,
    )

    parser.add_argument(
        "session_file",
        help="Session file path or session ID",
    )
    parser.add_argument(
        "--claude-home",
        type=str,
        help="Path to Claude home directory (default: ~/.claude or $CLAUDE_CONFIG_DIR)",
    )
    parser.add_argument(
        "--tree",
        "-t",
        action="store_true",
        help="Display results as a tree",
    )
    parser.add_argument(
        "--search-dir",
        "-d",
        help="Custom directory to search for trimmed sessions",
    )
    parser.add_argument(
        "--stats",
        "-s",
        action="store_true",
        help="Show statistics from trim_metadata",
    )

    args = parser.parse_args()

    # Resolve session file
    try:
        session_path = resolve_session_path(args.session_file, claude_home=args.claude_home)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Get search directories
    search_dir = Path(args.search_dir) if args.search_dir else None
    search_dirs = get_search_dirs(search_dir, claude_home=args.claude_home)

    # Find all descendants
    lineage = find_all_descendants(session_path, search_dirs)

    # Collect all trimmed sessions
    all_trimmed = []
    for children in lineage.values():
        all_trimmed.extend(children)

    if not all_trimmed:
        print(f"No trimmed sessions found for: {session_path}")
        sys.exit(0)

    # Display results
    if args.tree:
        print(f"{session_path}")
        print_tree(lineage, session_path)
    else:
        for trimmed in sorted(all_trimmed):
            print(trimmed)

    # Show statistics if requested
    if args.stats:
        print("\n" + "=" * 70)
        print("TRIM STATISTICS")
        print("=" * 70)

        for trimmed in sorted(all_trimmed):
            try:
                with open(trimmed) as f:
                    first_line = f.readline().strip()
                data = json.loads(first_line)

                if "trim_metadata" in data:
                    trim_meta = data["trim_metadata"]
                    stats = trim_meta.get("stats", {})
                    params = trim_meta.get("trim_params", {})

                    print(f"\nFile: {trimmed}")
                    print(
                        f"  Tools trimmed: {stats.get('num_tools_trimmed', 0)}"
                    )
                    print(
                        f"  Assistant msgs trimmed: "
                        f"{stats.get('num_assistant_trimmed', 0)}"
                    )
                    print(
                        f"  Tokens saved: {stats.get('tokens_saved', 0):,}"
                    )
                    print(f"  Threshold: {params.get('threshold', 'N/A')}")
                    if params.get("tools"):
                        print(
                            f"  Tools: {', '.join(params.get('tools', []))}"
                        )
                    if params.get("trim_assistant_messages"):
                        print(
                            f"  Assistant trim mode: "
                            f"{params.get('trim_assistant_messages')}"
                        )
            except (json.JSONDecodeError, IOError):
                continue

        print("=" * 70)


if __name__ == "__main__":
    main()
