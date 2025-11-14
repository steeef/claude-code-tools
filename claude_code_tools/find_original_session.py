#!/usr/bin/env python3
"""
Find the original (untrimmed) session by following parent links.

Given a session file (trimmed or original), follow the parent_file links
in trim_metadata backwards until reaching the original session.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


def find_original_session(session_file: Path) -> Path:
    """
    Follow parent links to find the original session.

    Args:
        session_file: Path to a session file (trimmed or original).

    Returns:
        Path to the original (root) session file.

    Raises:
        ValueError: If circular reference detected.
        FileNotFoundError: If parent file not found.
    """
    current = session_file.absolute()
    visited = set()

    while True:
        if current in visited:
            raise ValueError(f"Circular reference detected at {current}")
        visited.add(current)

        if not current.exists():
            raise FileNotFoundError(f"Session file not found: {current}")

        # Read first line to check for trim_metadata
        try:
            with open(current) as f:
                first_line = f.readline().strip()
        except IOError as e:
            raise IOError(f"Failed to read {current}: {e}")

        # Try to parse as JSON
        try:
            data = json.loads(first_line)
        except json.JSONDecodeError:
            # Not JSON - this is the original
            return current

        # Check if this has trim_metadata field
        if "trim_metadata" in data:
            trim_meta = data["trim_metadata"]
            parent_file = trim_meta.get("parent_file")
            if parent_file:
                current = Path(parent_file)
                continue

        # No parent found, this is the original
        return current


def main() -> None:
    """Parse arguments and find original session."""
    parser = argparse.ArgumentParser(
        description="Find original session by following parent links.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Find original session from a trimmed session
  %(prog)s ~/.claude/sessions/abc123.jsonl

  # Find original from a multi-level trimmed session
  %(prog)s /tmp/trimmed-session.jsonl
        """,
    )

    parser.add_argument(
        "session_file",
        help="Path to session file (trimmed or original)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show parent chain traversal",
    )

    args = parser.parse_args()

    # Validate input file
    session_path = Path(args.session_file)
    if not session_path.exists():
        print(
            f"Error: Session file '{args.session_file}' not found.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Find original
    try:
        if args.verbose:
            print("Following parent links...", file=sys.stderr)
            current = session_path.absolute()
            visited = []

            while True:
                visited.append(str(current))

                with open(current) as f:
                    first_line = f.readline().strip()

                try:
                    data = json.loads(first_line)
                    if "trim_metadata" in data:
                        trim_meta = data["trim_metadata"]
                        parent_file = trim_meta.get("parent_file")
                        if parent_file:
                            current = Path(parent_file)
                            continue
                except json.JSONDecodeError:
                    pass

                break

            print("\nParent chain:", file=sys.stderr)
            for i, path in enumerate(visited):
                indent = "  " * i
                arrow = "└─> " if i > 0 else ""
                print(f"{indent}{arrow}{path}", file=sys.stderr)
            print(file=sys.stderr)

        original = find_original_session(session_path)
        print(original)

    except (ValueError, FileNotFoundError, IOError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
