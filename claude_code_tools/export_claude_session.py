#!/usr/bin/env python3
"""Export Claude Code session to clean markdown format."""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, TextIO


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
    base_dir = Path(claude_home).expanduser() if claude_home else Path.home() / ".claude"

    # First try current project directory
    cwd = os.getcwd()
    encoded_path = cwd.replace("/", "-")
    claude_project_dir = base_dir / "projects" / encoded_path
    claude_path = claude_project_dir / f"{session_id}.jsonl"

    if claude_path.exists():
        return claude_path

    # Search all project directories
    projects_dir = base_dir / "projects"
    if projects_dir.exists():
        for project_dir in projects_dir.iterdir():
            if project_dir.is_dir():
                session_path = project_dir / f"{session_id}.jsonl"
                if session_path.exists():
                    return session_path

    # Not found
    raise FileNotFoundError(
        f"Session '{session_id}' not found in any Claude project directory under {projects_dir}"
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
    Export Claude Code session to markdown format.

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

            # Skip non-message types
            msg_type = data.get("type")
            if msg_type not in ["user", "assistant"]:
                stats["skipped"] += 1
                continue

            # Get message content
            message = data.get("message", {})
            role = message.get("role")
            content = message.get("content")

            if not content:
                stats["skipped"] += 1
                continue

            # Handle string content (older format or simple messages)
            if isinstance(content, str):
                if role == "user":
                    output_file.write("# USER\n\n")
                    output_file.write(f"{content.strip()}\n\n")
                    stats["user_messages"] += 1
                elif role == "assistant":
                    output_file.write("# ASSISTANT\n\n")
                    output_file.write(f"{content.strip()}\n\n")
                    stats["assistant_messages"] += 1
                continue

            # Handle list of content blocks
            if not isinstance(content, list):
                stats["skipped"] += 1
                continue

            # Process each content block
            for content_block in content:
                if isinstance(content_block, str):
                    # String content block
                    if role == "user":
                        output_file.write("# USER\n\n")
                        output_file.write(f"{content_block.strip()}\n\n")
                        stats["user_messages"] += 1
                    elif role == "assistant":
                        output_file.write("# ASSISTANT\n\n")
                        output_file.write(f"{content_block.strip()}\n\n")
                        stats["assistant_messages"] += 1
                    continue

                if not isinstance(content_block, dict):
                    stats["skipped"] += 1
                    continue

                block_type = content_block.get("type")

                # USER TEXT MESSAGE
                if role == "user" and block_type == "text":
                    text = content_block.get("text", "").strip()
                    if text:
                        output_file.write("# USER\n\n")
                        output_file.write(f"{text}\n\n")
                        stats["user_messages"] += 1

                # ASSISTANT TEXT MESSAGE
                elif role == "assistant" and block_type == "text":
                    text = content_block.get("text", "").strip()
                    if text:
                        output_file.write("# ASSISTANT\n\n")
                        output_file.write(f"{text}\n\n")
                        stats["assistant_messages"] += 1

                # TOOL CALL
                elif role == "assistant" and block_type == "tool_use":
                    output_file.write("# ASSISTANT - TOOL\n\n")
                    output_file.write(format_tool_use(content_block))
                    output_file.write("\n\n")
                    stats["tool_calls"] += 1

                # TOOL RESULT
                elif role == "user" and block_type == "tool_result":
                    output_file.write("# USER - TOOL RESULT\n\n")
                    output_file.write(format_tool_result(content_block))
                    output_file.write("\n\n")
                    stats["tool_results"] += 1

                else:
                    # Skip thinking blocks, reasoning, etc.
                    stats["skipped"] += 1

    return stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Export Claude Code session to clean markdown format"
    )
    parser.add_argument(
        "session_file",
        nargs='?',
        help="Session file path or session ID (optional - uses $CLAUDE_SESSION_ID if not provided)"
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        type=Path,
        help="Output markdown file path"
    )
    parser.add_argument(
        "--claude-home",
        type=str,
        help="Path to Claude home directory (default: ~/.claude)"
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
        # Try to get session ID from environment variable
        session_id = os.environ.get('CLAUDE_SESSION_ID')
        if not session_id:
            print(f"Error: No session file provided and CLAUDE_SESSION_ID not set", file=sys.stderr)
            print(f"Usage: export-claude-session <session-file-or-id> --output <file.md>", file=sys.stderr)
            sys.exit(1)

        # Reconstruct Claude Code session file path
        cwd = os.getcwd()
        base_dir = Path(args.claude_home).expanduser() if args.claude_home else Path.home() / ".claude"
        encoded_path = cwd.replace("/", "-")
        claude_project_dir = base_dir / "projects" / encoded_path
        session_file = claude_project_dir / f"{session_id}.jsonl"

        if not session_file.exists():
            print(f"Error: Session file not found: {session_file}", file=sys.stderr)
            print(f"(Reconstructed from CLAUDE_SESSION_ID={session_id})", file=sys.stderr)
            sys.exit(1)

        if args.verbose:
            print(f"📋 Using current Claude Code session: {session_id}")
    else:
        # Resolve session ID or path to full path
        try:
            session_file = resolve_session_path(args.session_file, claude_home=args.claude_home)
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
