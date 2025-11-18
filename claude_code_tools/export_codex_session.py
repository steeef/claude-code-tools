#!/usr/bin/env python3
"""Export Codex session using Claude Code's built-in export format."""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO


def export_session_programmatic(
    session_id_or_path: str,
    output_path: Optional[Path] = None,
    codex_home: Optional[str] = None,
    verbose: bool = False
) -> Path:
    """
    Export a Codex session programmatically.

    This is a programmatic interface to the export functionality, useful for
    other tools that need to export sessions and get the output path.

    Args:
        session_id_or_path: Session file path or session ID (full or partial)
        output_path: Optional output file path. If None, auto-generates in
            exported-sessions/ directory
        codex_home: Optional custom Codex home directory
        verbose: If True, print progress messages

    Returns:
        Path to the exported file

    Raises:
        FileNotFoundError: If session cannot be found
        SystemExit: If partial ID matches multiple sessions
    """
    # Resolve session file
    session_file = resolve_session_path(session_id_or_path, codex_home=codex_home)

    # Generate default output path if not provided
    if output_path is None:
        today = datetime.now().strftime("%Y%m%d")
        session_id = session_file.stem
        output_dir = Path.cwd() / "exported-sessions"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{today}-codex-session-{session_id}.txt"

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"📄 Exporting session: {session_file.name}")
        print(f"📝 Output file: {output_path}")
        print()

    # Export to file
    with open(output_path, 'w') as f:
        stats = export_session_to_markdown(session_file, f, verbose=verbose)

    if verbose:
        # Print statistics
        print(f"✅ Export complete!")
        print(f"   User messages: {stats['user_messages']}")
        print(f"   Assistant messages: {stats['assistant_messages']}")
        print(f"   Tool calls: {stats['tool_calls']}")
        print(f"   Tool results: {stats['tool_results']}")
        print(f"   Skipped items: {stats['skipped']}")
        print()
        print(f"📄 Exported to: {output_path}")

    return output_path


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


def simplify_tool_args(tool_input: dict) -> str:
    """
    Simplify tool arguments for compact display.

    Args:
        tool_input: Tool input dictionary

    Returns:
        Simplified string representation of arguments
    """
    if not tool_input:
        return ""

    # Common single-argument tools - just show the value
    if len(tool_input) == 1:
        key, value = list(tool_input.items())[0]
        # For common args like 'command', 'file_path', 'pattern', etc., just show the value
        if key in ['command', 'file_path', 'pattern', 'path', 'query', 'url', 'prompt']:
            if isinstance(value, str) and len(value) < 100:
                return value

    # For multiple arguments or complex cases, show key=value pairs
    parts = []
    for key, value in tool_input.items():
        if isinstance(value, str):
            # Quote if contains spaces or special chars
            if ' ' in value or any(c in value for c in [',', '(', ')']):
                parts.append(f'{key}="{value}"')
            else:
                parts.append(f'{key}={value}')
        elif isinstance(value, bool):
            parts.append(f'{key}={str(value).lower()}')
        elif isinstance(value, (int, float)):
            parts.append(f'{key}={value}')
        else:
            # For complex types, use compact JSON
            parts.append(f'{key}={json.dumps(value)}')

    return ', '.join(parts)


def indent_continuation(text: str, indent: str = "   ") -> str:
    """
    Indent continuation lines in multi-line text.

    Args:
        text: Text to process
        indent: Indent string for continuation lines

    Returns:
        Text with continuation lines indented
    """
    lines = text.split('\n')
    if len(lines) <= 1:
        return text

    # First line stays as-is, rest get indented
    result = [lines[0]]
    result.extend(indent + line for line in lines[1:])
    return '\n'.join(result)


def export_session_to_markdown(
    session_file: Path,
    output_file: TextIO,
    verbose: bool = False
) -> dict:
    """
    Export Codex session using Claude Code's built-in export format.

    Format:
        User messages: "> " prefix on first line, plain text continuation
        Assistant messages: "⏺ " prefix on first line, plain text continuation
        Tool calls: "⏺ ToolName(args)"
        Tool results: "  ⎿  output" with indented continuation lines

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
                        lines = text.split('\n')
                        output_file.write(f"> {lines[0]}\n")
                        for line in lines[1:]:
                            output_file.write(f"{line}\n")
                        output_file.write("\n")
                        stats["user_messages"] += 1

                    # ASSISTANT TEXT MESSAGE (output_text)
                    elif role == "assistant" and block_type == "output_text" and text:
                        lines = text.split('\n')
                        output_file.write(f"⏺ {lines[0]}\n")
                        for line in lines[1:]:
                            output_file.write(f"{line}\n")
                        output_file.write("\n")
                        stats["assistant_messages"] += 1

            # Process FUNCTION_CALL type
            elif payload_type == "function_call":
                tool_name = payload.get("name", "Unknown")
                arguments = payload.get("arguments", "{}")

                # Parse arguments if it's a JSON string
                try:
                    args_dict = json.loads(arguments) if isinstance(arguments, str) else arguments
                except:
                    args_dict = {}

                # Format in Claude Code style
                args_str = simplify_tool_args(args_dict)
                if args_str:
                    output_file.write(f"⏺ {tool_name}({args_str})\n\n")
                else:
                    output_file.write(f"⏺ {tool_name}()\n\n")
                stats["tool_calls"] += 1

            # Process CUSTOM_TOOL_CALL type
            elif payload_type == "custom_tool_call":
                tool_name = payload.get("name", "Unknown")
                tool_input = payload.get("input", "")

                # Parse input if it's JSON
                try:
                    if isinstance(tool_input, str):
                        args_dict = json.loads(tool_input)
                    else:
                        args_dict = tool_input if isinstance(tool_input, dict) else {}
                except:
                    args_dict = {}

                args_str = simplify_tool_args(args_dict)
                if args_str:
                    output_file.write(f"⏺ {tool_name}({args_str})\n\n")
                else:
                    output_file.write(f"⏺ {tool_name}()\n\n")
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

                # Format with hooked arrow and indented continuation
                if not actual_output:
                    output_file.write("  ⎿  (No content)\n\n")
                else:
                    text = str(actual_output)
                    indented = indent_continuation(text, indent="     ")
                    output_file.write(f"  ⎿  {indented}\n\n")
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

                # Format with hooked arrow and indented continuation
                if not actual_output:
                    output_file.write("  ⎿  (No content)\n\n")
                else:
                    text = str(actual_output)
                    indented = indent_continuation(text, indent="     ")
                    output_file.write(f"  ⎿  {indented}\n\n")
                stats["tool_results"] += 1

            # Skip other types (reasoning, event_msg, session_meta, turn_context, etc.)
            else:
                stats["skipped"] += 1

    return stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Export Codex session using Claude Code's built-in format"
    )
    parser.add_argument(
        "session_file",
        nargs='?',
        help="Session file path or session ID"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output text file path (.txt) - defaults to exported-sessions/YYYYMMDD-codex-session-<id>.txt"
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

    # Generate default output path if not provided
    if args.output is None:
        today = datetime.now().strftime("%Y%m%d")
        session_id = session_file.stem  # Get filename without extension
        output_dir = Path.cwd() / "exported-sessions"
        output_dir.mkdir(parents=True, exist_ok=True)
        args.output = output_dir / f"{today}-codex-session-{session_id}.txt"

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
