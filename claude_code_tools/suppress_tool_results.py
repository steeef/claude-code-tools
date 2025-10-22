#!/usr/bin/env python3
"""
Suppress large tool results in CLI agent JSONL session files.

This script processes JSONL session logs from Claude Code or Codex and
replaces large tool results with placeholder text to reduce file size while
preserving conversation flow.
"""

import argparse
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Set, Tuple

from . import suppress_tool_results_claude as claude_processor
from . import suppress_tool_results_codex as codex_processor


def create_placeholder(tool_name: str, original_length: int) -> str:
    """
    Create a placeholder string for suppressed content.

    Args:
        tool_name: Name of the tool.
        original_length: Original content length in characters.

    Returns:
        Placeholder string.
    """
    return (
        f"[Results from {tool_name} tool suppressed - "
        f"original content was {original_length:,} characters]"
    )


def process_session(
    agent: str,
    input_file: Path,
    output_file: Path,
    target_tools: Optional[Set[str]],
    threshold: int,
) -> Tuple[int, int]:
    """
    Process session file and suppress tool results.

    Args:
        agent: Agent type ('claude' or 'codex').
        input_file: Path to input JSONL file.
        output_file: Path to output JSONL file.
        target_tools: Set of tool names to suppress (None means all).
        threshold: Minimum length threshold for suppression.

    Returns:
        Tuple of (num_suppressed, chars_saved).
    """
    print("Building tool name mapping...", file=sys.stderr)

    if agent == "claude":
        tool_map = claude_processor.build_tool_name_mapping(input_file)
        print(
            f"Found {len(tool_map)} tool invocations", file=sys.stderr
        )
        print("Processing tool results...", file=sys.stderr)

        return claude_processor.process_claude_session(
            input_file,
            output_file,
            tool_map,
            target_tools,
            threshold,
            create_placeholder,
        )
    elif agent == "codex":
        tool_map = codex_processor.build_tool_name_mapping(input_file)
        print(
            f"Found {len(tool_map)} tool invocations", file=sys.stderr
        )
        print("Processing tool results...", file=sys.stderr)

        return codex_processor.process_codex_session(
            input_file,
            output_file,
            tool_map,
            target_tools,
            threshold,
            create_placeholder,
        )
    else:
        raise ValueError(f"Unknown agent type: {agent}")


def main() -> None:
    """Parse arguments and process the JSONL file."""
    parser = argparse.ArgumentParser(
        description="Suppress large tool results in JSONL session files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Suppress all tool results over 500 chars in Claude session
  %(prog)s session.jsonl

  # Suppress Codex session results
  %(prog)s session.jsonl --agent codex

  # Suppress only specific tools
  %(prog)s session.jsonl --tools bash,read,edit

  # Use custom length threshold
  %(prog)s session.jsonl --len 1000

  # Suppress Task tool results over 1000 chars
  %(prog)s session.jsonl --tools task --len 1000

  # Custom output directory
  %(prog)s session.jsonl --output-dir /tmp
        """,
    )

    parser.add_argument(
        "input_file", help="Input JSONL session file path"
    )
    parser.add_argument(
        "--agent",
        "-a",
        choices=["claude", "codex"],
        default="claude",
        help="Agent type: claude or codex (default: claude)",
    )
    parser.add_argument(
        "--tools",
        "-t",
        help="Comma-separated list of tool names to suppress "
        "(e.g., 'bash,read,edit'). If not specified, all tools are "
        "candidates for suppression.",
    )
    parser.add_argument(
        "--len",
        "-l",
        type=int,
        default=500,
        help="Minimum length threshold in characters for suppression "
        "(default: 500)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        help="Output directory (default: same as input file)",
    )

    args = parser.parse_args()

    # Validate input file
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(
            f"Error: Input file '{args.input_file}' not found.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Parse tool names
    target_tools = None
    if args.tools:
        target_tools = {
            tool.strip().lower() for tool in args.tools.split(",")
        }
        print(
            f"Suppressing tools: {', '.join(sorted(target_tools))}",
            file=sys.stderr,
        )
    else:
        print(
            "Suppressing all tools (no --tools specified)",
            file=sys.stderr,
        )

    print(
        f"Agent: {args.agent}", file=sys.stderr
    )
    print(
        f"Length threshold: {args.len} characters", file=sys.stderr
    )

    # Generate output filename and directory based on agent type
    session_uuid = str(uuid.uuid4())

    if args.agent == "codex":
        # Codex format: YYYY/MM/DD/rollout-YYYY-MM-DDTHH-MM-SS-{uuid}.jsonl
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%dT%H-%M-%S")
        date_path = now.strftime("%Y/%m/%d")
        output_filename = f"rollout-{timestamp}-{session_uuid}{input_path.suffix}"

        # Determine base directory for Codex
        if args.output_dir:
            # User specified output directory
            output_dir = Path(args.output_dir) / date_path
        else:
            # Find sessions root by going up from input file
            # Structure: ~/.codex/sessions/YYYY/MM/DD/file.jsonl
            # Go up 3 levels to get to sessions directory
            sessions_root = input_path.parent.parent.parent.parent
            output_dir = sessions_root / date_path

        # Create date-based directory structure
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        # Claude format: {uuid}.jsonl
        output_dir = (
            Path(args.output_dir) if args.output_dir else input_path.parent
        )
        output_filename = f"{session_uuid}{input_path.suffix}"

    output_path = output_dir / output_filename

    # Process the file
    print(f"\nInput: {input_path}", file=sys.stderr)
    print(f"Output: {output_path}", file=sys.stderr)
    print("", file=sys.stderr)

    num_suppressed, chars_saved = process_session(
        args.agent, input_path, output_path, target_tools, args.len
    )

    # Estimate tokens saved using heuristic (4 chars per token)
    tokens_saved = int(chars_saved / 4)

    # Print statistics
    print("\n" + "=" * 70)
    print("SUPPRESSION SUMMARY")
    print("=" * 70)
    print(f"Agent: {args.agent}")
    print(f"Tool results suppressed: {num_suppressed}")
    print(f"Characters saved: {chars_saved:,}")
    print(f"Estimated tokens saved: {tokens_saved:,}")
    print("")
    print(f"Output file: {output_path}")
    print("")
    print("Session UUID:")
    print(session_uuid)
    print("=" * 70)


if __name__ == "__main__":
    main()
