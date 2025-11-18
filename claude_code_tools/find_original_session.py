#!/usr/bin/env python3
"""
Find the original session by following parent links.

Given a session file (trimmed, continued, or original), follow the parent_file
or parent_session_file links in trim_metadata/continue_metadata backwards
until reaching the original session.
"""

import argparse
import sys
from pathlib import Path

from claude_code_tools.session_lineage import (
    get_full_lineage_chain,
    get_parent_info,
)
from claude_code_tools.session_utils import resolve_session_path


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
    if not session_file.exists():
        raise FileNotFoundError(f"Session file not found: {session_file}")

    # Get the full lineage chain (newest to oldest)
    chain = get_full_lineage_chain(session_file)

    # The last item in the chain is the original
    if chain:
        return chain[-1][0]

    # If chain is empty, the current file is the original
    return session_file


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
        help="Session file path or session ID",
    )
    parser.add_argument(
        "--claude-home",
        type=str,
        help="Path to Claude home directory (default: ~/.claude or $CLAUDE_CONFIG_DIR)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show parent chain traversal",
    )

    args = parser.parse_args()

    # Resolve session file
    try:
        session_path = resolve_session_path(args.session_file, claude_home=args.claude_home)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Find original
    try:
        if args.verbose:
            print("Following parent links...", file=sys.stderr)

            # Get the full lineage chain
            chain = get_full_lineage_chain(session_path)

            print("\nParent chain:", file=sys.stderr)
            for i, (path, derivation_type) in enumerate(chain):
                indent = "  " * i
                arrow = "└─> " if i > 0 else ""
                type_label = (
                    f" ({derivation_type})"
                    if derivation_type != "original"
                    else ""
                )
                print(
                    f"{indent}{arrow}{path}{type_label}", file=sys.stderr
                )

                # Show exported log if this is a continued session
                if derivation_type == "continued":
                    _, _, exported_file = get_parent_info(path)
                    if exported_file:
                        # Make exported file path absolute if needed
                        if not exported_file.is_absolute():
                            abs_exported = path.parent / exported_file
                            if abs_exported.exists():
                                exported_file = abs_exported
                        print(
                            f"{indent}    Exported chat: {exported_file}",
                            file=sys.stderr,
                        )
            print(file=sys.stderr)

        original = find_original_session(session_path)
        print(original)

    except (ValueError, FileNotFoundError, IOError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
