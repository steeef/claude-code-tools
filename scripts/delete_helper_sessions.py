#!/usr/bin/env python3
"""
Delete helper sessions created by smart-trim and query operations.

Helper sessions are identified by:
1. Having few user messages (lines <= 5 in the index)
   - Claude helpers: lines=1
   - Codex helpers: lines=3 (due to system messages counted as user)
2. Containing one of the known helper patterns in the content

Patterns:
- Smart-trim: "You are analyzing a coding agent session"
- Query: "There is a log of a past conversation with an AI agent in this file:"
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from claude_code_tools.search_index import SessionIndex

# Patterns that identify helper sessions
HELPER_PATTERNS = [
    "You are analyzing a coding agent session",
    "There is a log of a past conversation with an AI agent in this file:",
]


def check_helper_pattern(session_file: Path) -> str | None:
    """
    Check if session file contains a helper pattern.

    Args:
        session_file: Path to session JSONL file

    Returns:
        The matched pattern string, or None if no match
    """
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            # Read first few KB to check for patterns (they appear early)
            content = f.read(50000)
            for pattern in HELPER_PATTERNS:
                if pattern in content:
                    return pattern
    except (OSError, IOError):
        pass
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Delete helper sessions created by smart-trim and query operations"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    parser.add_argument(
        "--index-path",
        type=Path,
        default=None,
        help="Path to search index (default: ~/.cctools/search-index)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )
    args = parser.parse_args()

    # Open the index
    index_path = args.index_path or Path.home() / ".cctools" / "search-index"
    if not index_path.exists():
        print(f"Error: Index not found at {index_path}", file=sys.stderr)
        print("Run 'aichat search' first to build the index.", file=sys.stderr)
        sys.exit(1)

    print(f"Loading index from {index_path}...")
    index = SessionIndex(index_path)

    # Get all sessions - use a high limit to get everything
    print("Querying for sessions with lines <= 5...")
    all_results = index.search("", limit=10000)

    # Filter to sessions with few user messages (likely helpers)
    # Claude helpers have lines=1, Codex helpers have lines=3 (due to system messages)
    candidate_sessions = [r for r in all_results if r.get("lines", 0) <= 5]
    print(f"Found {len(candidate_sessions)} sessions with lines <= 5")

    # Check each for helper patterns
    helper_sessions = []
    for result in candidate_sessions:
        session_id = result.get("session_id")
        agent = result.get("agent")
        export_path = result.get("export_path")

        if not session_id or not export_path:
            continue

        session_file = Path(export_path)
        if not session_file.exists():
            if args.verbose:
                print(f"  Session file not found: {export_path}")
            continue

        pattern = check_helper_pattern(session_file)
        if pattern:
            helper_sessions.append({
                "session_id": session_id,
                "session_file": session_file,
                "pattern": pattern,
                "agent": agent,
            })

    print(f"\nFound {len(helper_sessions)} helper sessions to delete:")

    if not helper_sessions:
        print("No helper sessions found.")
        return

    # Group by pattern for summary
    smart_trim_count = sum(
        1 for s in helper_sessions if "analyzing a coding agent" in s["pattern"]
    )
    query_count = sum(
        1 for s in helper_sessions if "log of a past conversation" in s["pattern"]
    )
    print(f"  - Smart-trim helpers: {smart_trim_count}")
    print(f"  - Query helpers: {query_count}")
    print()

    if args.verbose or args.dry_run:
        for session in helper_sessions:
            pattern_short = (
                "smart-trim"
                if "analyzing a coding agent" in session["pattern"]
                else "query"
            )
            print(f"  [{pattern_short}] {session['session_file']}")

    if args.dry_run:
        print("\n[DRY RUN] No files were deleted.")
        print("Run without --dry-run to delete these files.")
        return

    # Delete the sessions
    print("\nDeleting helper sessions...")
    deleted = 0
    errors = 0
    for session in helper_sessions:
        try:
            session["session_file"].unlink()
            deleted += 1
            if args.verbose:
                print(f"  Deleted: {session['session_file']}")
        except OSError as e:
            errors += 1
            print(f"  Error deleting {session['session_file']}: {e}", file=sys.stderr)

    print(f"\nDone! Deleted {deleted} helper sessions.")
    if errors:
        print(f"  ({errors} errors occurred)")

    print("\nNote: Run 'aichat search --reindex' to update the search index.")


if __name__ == "__main__":
    main()
