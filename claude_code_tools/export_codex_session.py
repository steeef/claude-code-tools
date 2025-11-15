#!/usr/bin/env python3
"""Export Codex session to clean markdown format."""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, TextIO


def resolve_session_path(session_id_or_path: str, codex_home: Optional[str] = None) -> Path:
    """
    Resolve a session ID or path to a full file path.

    Args:
        session_id_or_path: Either a full path or a session UUID
        codex_home: Optional custom Codex home directory (defaults to ~/.codex)

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
    base_dir = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"

    # Search through Codex sessions directory (organized by date: YYYY/MM/DD)
    sessions_dir = base_dir / "sessions"
    if sessions_dir.exists():
        for jsonl_file in sessions_dir.rglob("*.jsonl"):
            if session_id in jsonl_file.name:
                return jsonl_file

    # Not found
    raise FileNotFoundError(
        f"Session '{session_id}' not found in Codex sessions directory: {sessions_dir}"
    )


def format_tool_use(content_block: dict) -> str:
    """
    Format a tool use content block.

    Args:
        content_block: Tool use content block

    Returns:
        Formatted string showing tool name and input
    """
    tool_name = content_block.get("name", "Unknown")
    tool_input = content_block.get("input", {})

    # Format the input nicely
    if isinstance(tool_input, dict):
        input_str = json.dumps(tool_input, indent=2)
    else:
        input_str = str(tool_input)

    return f"**Tool**: {tool_name}\n\n```json\n{input_str}\n```"


def format_tool_result(content_block: dict) -> str:
    """
    Format a tool result content block.

    Args:
        content_block: Tool result content block

    Returns:
        Formatted string showing tool output
    """
    content = content_block.get("content", "")

    # If content is a string, use it directly
    if isinstance(content, str):
        return f"```\n{content}\n```"

    # If content is a list, extract text
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return f"```\n{''.join(parts)}\n```"

    # Fallback
    return f"```\n{content}\n```"


def export_session_to_markdown(
    session_file: Path,
    output_file: TextIO,
    verbose: bool = False
) -> dict:
    """
    Export Codex session to markdown format.

    Args:
        session_file: Path to session JSONL file
        output_file: Output file handle
        verbose: If True, show progress

    Returns:
        Stats dict with counts
    """
    stats = {
        "user_messages": 0,
        "assistant_messages": 0,
        "tool_calls": 0,
        "tool_results": 0,
        "skipped": 0
    }

    with open(session_file, 'r') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                if verbose:
                    print(f"⚠️  Line {line_num}: Invalid JSON, skipping", file=sys.stderr)
                stats["skipped"] += 1
                continue

            # Only process response_item types
            msg_type = data.get("type")
            if msg_type != "response_item":
                stats["skipped"] += 1
                continue

            # Get payload
            payload = data.get("payload", {})
            payload_type = payload.get("type")

            # Process MESSAGE type (user or assistant)
            if payload_type == "message":
                role = payload.get("role")
                content = payload.get("content", [])

                if not isinstance(content, list):
                    stats["skipped"] += 1
                    continue

                for content_block in content:
                    if not isinstance(content_block, dict):
                        continue

                    block_type = content_block.get("type")
                    text = content_block.get("text", "").strip()

                    # USER TEXT MESSAGE (input_text)
                    if role == "user" and block_type == "input_text" and text:
                        output_file.write("# USER\n\n")
                        output_file.write(f"{text}\n\n")
                        stats["user_messages"] += 1

                    # ASSISTANT TEXT MESSAGE (output_text)
                    elif role == "assistant" and block_type == "output_text" and text:
                        output_file.write("# ASSISTANT\n\n")
                        output_file.write(f"{text}\n\n")
                        stats["assistant_messages"] += 1

            # Process FUNCTION_CALL type
            elif payload_type == "function_call":
                tool_name = payload.get("name", "Unknown")
                arguments = payload.get("arguments", "{}")

                # Parse arguments if it's a JSON string
                try:
                    args_dict = json.loads(arguments) if isinstance(arguments, str) else arguments
                    args_str = json.dumps(args_dict, indent=2)
                except:
                    args_str = str(arguments)

                output_file.write("# ASSISTANT - TOOL\n\n")
                output_file.write(f"**Tool**: {tool_name}\n\n```json\n{args_str}\n```\n\n")
                stats["tool_calls"] += 1

            # Process CUSTOM_TOOL_CALL type
            elif payload_type == "custom_tool_call":
                tool_name = payload.get("name", "Unknown")
                tool_input = payload.get("input", "")

                output_file.write("# ASSISTANT - TOOL\n\n")
                output_file.write(f"**Tool**: {tool_name}\n\n```\n{tool_input}\n```\n\n")
                stats["tool_calls"] += 1

            # Process FUNCTION_CALL_OUTPUT type
            elif payload_type == "function_call_output":
                output = payload.get("output", "")

                # Parse output if it's a JSON string
                try:
                    if isinstance(output, str):
                        output_dict = json.loads(output)
                        actual_output = output_dict.get("output", output)
                    else:
                        actual_output = output
                except:
                    actual_output = output

                output_file.write("# USER - TOOL RESULT\n\n")
                output_file.write(f"```\n{actual_output}\n```\n\n")
                stats["tool_results"] += 1

            # Process CUSTOM_TOOL_CALL_OUTPUT type
            elif payload_type == "custom_tool_call_output":
                output = payload.get("output", "")

                # Parse output if it's a JSON string
                try:
                    if isinstance(output, str):
                        output_dict = json.loads(output)
                        actual_output = output_dict.get("output", output)
                    else:
                        actual_output = output
                except:
                    actual_output = output

                output_file.write("# USER - TOOL RESULT\n\n")
                output_file.write(f"```\n{actual_output}\n```\n\n")
                stats["tool_results"] += 1

            # Skip other types (reasoning, event_msg, session_meta, turn_context, etc.)
            else:
                stats["skipped"] += 1

    return stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Export Codex session to clean markdown format"
    )
    parser.add_argument(
        "session_file",
        nargs='?',
        help="Session file path or session ID"
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        type=Path,
        help="Output markdown file path"
    )
    parser.add_argument(
        "--codex-home",
        type=str,
        help="Path to Codex home directory (default: ~/.codex)"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show progress and statistics"
    )

    args = parser.parse_args()

    # Handle session file resolution
    if args.session_file is None:
        print(f"Error: No session file provided", file=sys.stderr)
        print(f"Usage: export-codex-session <session-file-or-id> --output <file.md>", file=sys.stderr)
        sys.exit(1)

    # Resolve session ID or path to full path
    try:
        session_file = resolve_session_path(args.session_file, codex_home=args.codex_home)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)

    if args.verbose:
        print(f"📄 Exporting session: {session_file.name}")
        print(f"📝 Output file: {args.output}")
        print()

    # Export to markdown
    with open(args.output, 'w') as f:
        stats = export_session_to_markdown(session_file, f, verbose=args.verbose)

    # Print statistics
    print(f"✅ Export complete!")
    print(f"   User messages: {stats['user_messages']}")
    print(f"   Assistant messages: {stats['assistant_messages']}")
    print(f"   Tool calls: {stats['tool_calls']}")
    print(f"   Tool results: {stats['tool_results']}")
    print(f"   Skipped items: {stats['skipped']}")
    print()
    print(f"📄 Output: {args.output}")


if __name__ == "__main__":
    main()
