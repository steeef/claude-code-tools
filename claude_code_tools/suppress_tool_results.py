#!/usr/bin/env python3
"""
Suppress large tool results in Claude Code JSONL session files.

This script processes JSONL session logs and replaces large tool results
with placeholder text to reduce file size while preserving conversation flow.
"""

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


def build_tool_name_mapping(input_file: Path) -> Dict[str, str]:
    """
    Build a mapping of tool_use_id to tool name.

    Args:
        input_file: Path to the input JSONL file.

    Returns:
        Dictionary mapping tool_use_id to tool name.
    """
    tool_map = {}

    with open(input_file, "r") as f:
        for line in f:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            if data.get("type") != "assistant":
                continue

            content = data.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue

            for item in content:
                if (
                    isinstance(item, dict)
                    and item.get("type") == "tool_use"
                ):
                    tool_id = item.get("id")
                    tool_name = item.get("name")
                    if tool_id and tool_name:
                        tool_map[tool_id] = tool_name

    return tool_map


def get_content_length(content: Any) -> int:
    """
    Calculate the length of tool result content.

    Args:
        content: The content field from a tool_result.

    Returns:
        Length in characters.
    """
    if isinstance(content, str):
        return len(content)
    elif isinstance(content, list):
        total = 0
        for item in content:
            if isinstance(item, dict) and "text" in item:
                total += len(item["text"])
            else:
                total += len(str(item))
        return total
    else:
        return len(str(content))


def should_suppress(
    tool_name: str,
    content_length: int,
    target_tools: Optional[Set[str]],
    threshold: int,
) -> bool:
    """
    Determine if a tool result should be suppressed.

    Args:
        tool_name: Name of the tool.
        content_length: Length of the result content.
        target_tools: Set of tool names to suppress (None means all).
        threshold: Minimum length threshold for suppression.

    Returns:
        True if the result should be suppressed.
    """
    # Check length threshold
    if content_length < threshold:
        return False

    # Check if tool is in target list
    if target_tools is None:
        return True  # Suppress all tools over threshold

    return tool_name.lower() in target_tools


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


def process_jsonl(
    input_file: Path,
    output_file: Path,
    target_tools: Optional[Set[str]],
    threshold: int,
) -> Tuple[int, int]:
    """
    Process JSONL file and suppress tool results.

    Args:
        input_file: Path to input JSONL file.
        output_file: Path to output JSONL file.
        target_tools: Set of tool names to suppress (None means all).
        threshold: Minimum length threshold for suppression.

    Returns:
        Tuple of (num_suppressed, chars_saved).
    """
    print("Building tool name mapping...", file=sys.stderr)
    tool_map = build_tool_name_mapping(input_file)
    print(
        f"Found {len(tool_map)} tool invocations", file=sys.stderr
    )

    num_suppressed = 0
    chars_saved = 0

    print("Processing tool results...", file=sys.stderr)

    with open(input_file, "r") as infile, open(
        output_file, "w"
    ) as outfile:
        for line_num, line in enumerate(infile, start=1):
            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                print(
                    f"Warning: Skipping line {line_num} "
                    f"due to JSON error: {e}",
                    file=sys.stderr,
                )
                outfile.write(line)
                continue

            # Check if this is a user message with tool results
            if data.get("type") == "user":
                content = data.get("message", {}).get("content")

                # Handle array content with tool_result
                if isinstance(content, list):
                    for item in content:
                        if (
                            isinstance(item, dict)
                            and item.get("type") == "tool_result"
                        ):
                            tool_use_id = item.get("tool_use_id")
                            tool_name = tool_map.get(
                                tool_use_id, "Unknown"
                            )
                            result_content = item.get("content", "")

                            content_length = get_content_length(
                                result_content
                            )

                            if should_suppress(
                                tool_name,
                                content_length,
                                target_tools,
                                threshold,
                            ):
                                placeholder = create_placeholder(
                                    tool_name, content_length
                                )
                                item["content"] = placeholder
                                num_suppressed += 1
                                chars_saved += (
                                    content_length - len(placeholder)
                                )

                # Also suppress in toolUseResult.content if present
                if (
                    "toolUseResult" in data
                    and isinstance(data["toolUseResult"], dict)
                ):
                    tool_result = data["toolUseResult"]
                    if "content" in tool_result:
                        # Find the tool_use_id from message content
                        tool_use_id = None
                        if isinstance(content, list):
                            for item in content:
                                if item.get("type") == "tool_result":
                                    tool_use_id = item.get(
                                        "tool_use_id"
                                    )
                                    break

                        if tool_use_id:
                            tool_name = tool_map.get(
                                tool_use_id, "Unknown"
                            )
                            result_content = tool_result["content"]
                            content_length = get_content_length(
                                result_content
                            )

                            if should_suppress(
                                tool_name,
                                content_length,
                                target_tools,
                                threshold,
                            ):
                                placeholder = create_placeholder(
                                    tool_name, content_length
                                )
                                tool_result["content"] = placeholder

            # Write the (potentially modified) line
            outfile.write(json.dumps(data) + "\n")

    return num_suppressed, chars_saved


def main() -> None:
    """Parse arguments and process the JSONL file."""
    parser = argparse.ArgumentParser(
        description="Suppress large tool results in JSONL session files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Suppress all tool results over 500 chars (default)
  %(prog)s session.jsonl

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
        f"Length threshold: {args.len} characters", file=sys.stderr
    )

    # Generate output filename with UUID (same format as original)
    session_uuid = str(uuid.uuid4())
    output_dir = (
        Path(args.output_dir) if args.output_dir else input_path.parent
    )
    # Use just the UUID as filename (Claude Code session file format)
    output_filename = f"{session_uuid}{input_path.suffix}"
    output_path = output_dir / output_filename

    # Process the file
    print(f"\nInput: {input_path}", file=sys.stderr)
    print(f"Output: {output_path}", file=sys.stderr)
    print("", file=sys.stderr)

    num_suppressed, chars_saved = process_jsonl(
        input_path, output_path, target_tools, args.len
    )

    # Estimate tokens saved using heuristic (4 chars per token)
    tokens_saved = int(chars_saved / 4)

    # Print statistics
    print("\n" + "=" * 70)
    print("SUPPRESSION SUMMARY")
    print("=" * 70)
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
