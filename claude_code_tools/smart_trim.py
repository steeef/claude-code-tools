#!/usr/bin/env python3
"""Smart trim: LLM-powered intelligent session trimming."""

import argparse
import datetime
import json
import os
import sys
import uuid
from pathlib import Path
from typing import List, Optional

from claude_code_tools.smart_trim_core import identify_trimmable_lines
from claude_code_tools.trim_session import detect_agent
from claude_code_tools.session_utils import get_claude_home, resolve_session_path


def trim_lines(input_file: Path, line_indices: List[int], output_file: Path) -> dict:
    """
    Replace content within specified lines with placeholders.

    IMPORTANT: Never delete or replace entire message lines - this breaks the
    conversation structure that the Anthropic API requires. Instead, replace
    CONTENT fields (text, tool results, etc.) within messages.

    Args:
        input_file: Input session file
        line_indices: Line numbers to trim (0-indexed)
        output_file: Output file path

    Returns:
        Stats dict with num_lines_trimmed and chars_saved
    """
    with open(input_file, 'r') as f:
        lines = f.readlines()

    chars_saved = 0
    trimmed_count = 0

    # Process each line that should be trimmed
    for idx in sorted(line_indices):
        if 0 <= idx < len(lines):
            try:
                data = json.loads(lines[idx])
                original_len = len(lines[idx])

                # Determine message type and replace content appropriately
                msg_type = data.get("type", "")
                trimmed = False

                # Claude Code format
                if msg_type == "assistant":
                    # Replace text content in assistant messages
                    message = data.get("message", {})
                    content = message.get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text = item.get("text", "")
                                if text:
                                    item["text"] = f"[Content trimmed by smart-trim - {len(text):,} chars]"
                                    trimmed = True

                elif msg_type == "user":
                    # Replace tool result content
                    message = data.get("message", {})
                    content = message.get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "tool_result":
                                result_content = item.get("content", "")
                                if isinstance(result_content, str) and result_content:
                                    content_len = len(result_content)
                                    item["content"] = f"[Tool result trimmed by smart-trim - {content_len:,} chars]"
                                    trimmed = True
                                elif isinstance(result_content, list):
                                    # Handle list format
                                    total_len = sum(len(str(c)) for c in result_content)
                                    item["content"] = f"[Tool result trimmed by smart-trim - {total_len:,} chars]"
                                    trimmed = True

                # Codex format (response_item with payload)
                elif msg_type == "response_item":
                    payload = data.get("payload", {})
                    payload_type = payload.get("type", "")

                    if payload_type == "message":
                        # Replace message text content
                        content = payload.get("content", [])
                        if isinstance(content, list):
                            for item in content:
                                if isinstance(item, dict):
                                    text = item.get("text", "")
                                    if text:
                                        item["text"] = f"[Content trimmed by smart-trim - {len(text):,} chars]"
                                        trimmed = True

                    elif payload_type == "function_call_output":
                        # Replace function output
                        output = payload.get("output", "")
                        if output:
                            output_len = len(str(output))
                            payload["output"] = f"[Function output trimmed by smart-trim - {output_len:,} chars]"
                            trimmed = True

                # Codex old format
                elif msg_type == "message":
                    content = data.get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict):
                                text = item.get("text", "")
                                if text:
                                    item["text"] = f"[Content trimmed by smart-trim - {len(text):,} chars]"
                                    trimmed = True

                elif msg_type == "function_call_output":
                    output = data.get("output", "")
                    if output:
                        output_len = len(str(output))
                        data["output"] = f"[Function output trimmed by smart-trim - {output_len:,} chars]"
                        trimmed = True

                if trimmed:
                    # Write modified line
                    new_line = json.dumps(data) + "\n"
                    chars_saved += original_len - len(new_line)
                    lines[idx] = new_line
                    trimmed_count += 1

            except json.JSONDecodeError:
                # Skip malformed lines - don't modify them
                pass

    # Write output
    with open(output_file, 'w') as f:
        f.writelines(lines)

    return {
        "num_lines_trimmed": trimmed_count,
        "chars_saved": chars_saved,
        "tokens_saved": chars_saved // 4  # Rough estimate
    }


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Intelligently trim session files using LLM analysis"
    )
    parser.add_argument(
        "session_file",
        nargs='?',
        help="Session file path or session ID (optional - uses $CLAUDE_SESSION_ID if not provided)"
    )
    parser.add_argument(
        "--exclude-types",
        default="user",
        help="Comma-separated message types to never trim (default: user)"
    )
    parser.add_argument(
        "--preserve-recent",
        type=int,
        default=10,
        help="Always preserve last N messages (default: 10, deprecated - use --preserve-tail)"
    )
    parser.add_argument(
        "--preserve-head",
        type=int,
        default=0,
        help="Always preserve first N messages (default: 0)"
    )
    parser.add_argument(
        "--preserve-tail",
        type=int,
        default=None,
        help="Always preserve last N messages (default: None, uses --preserve-recent)"
    )
    parser.add_argument(
        "--max-lines-per-agent",
        type=int,
        default=100,
        help="Maximum lines per agent chunk for parallel processing (default: 100)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory (default: same as input)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be trimmed without doing it"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show rationale for each trimmed line"
    )
    parser.add_argument(
        "--content-threshold",
        type=int,
        default=200,
        help="Minimum characters for content extraction (default: 200)"
    )
    parser.add_argument(
        "--claude-home",
        type=str,
        help="Path to Claude home directory (default: ~/.claude)"
    )

    args = parser.parse_args()

    # Handle session file resolution
    if args.session_file is None:
        # Try to get session ID from environment variable
        session_id = os.environ.get('CLAUDE_SESSION_ID')
        if not session_id:
            print(f"Error: No session file provided and CLAUDE_SESSION_ID not set", file=sys.stderr)
            print(f"Usage: smart-trim <session-file-or-id> or run from within Claude Code with !smart-trim", file=sys.stderr)
            sys.exit(1)

        # Reconstruct Claude Code session file path
        cwd = os.getcwd()
        base_dir = get_claude_home(args.claude_home)
        encoded_path = cwd.replace("/", "-")
        claude_project_dir = base_dir / "projects" / encoded_path
        session_file = claude_project_dir / f"{session_id}.jsonl"

        if not session_file.exists():
            print(f"Error: Session file not found: {session_file}", file=sys.stderr)
            print(f"(Reconstructed from CLAUDE_SESSION_ID={session_id})", file=sys.stderr)
            sys.exit(1)

        print(f"📋 Using current Claude Code session: {session_id}")
    else:
        # Resolve session ID or path to full path
        try:
            session_file = resolve_session_path(args.session_file, claude_home=args.claude_home)
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    # Parse exclude types
    exclude_types = [t.strip() for t in args.exclude_types.split(",")]

    print(f"🔍 Analyzing session: {session_file.name}")
    print(f"   Excluding types: {', '.join(exclude_types)}")
    if args.preserve_head > 0:
        print(f"   Preserving head: {args.preserve_head} messages")
    if args.preserve_tail is not None:
        print(f"   Preserving tail: {args.preserve_tail} messages")
    else:
        print(f"   Preserving recent: {args.preserve_recent} messages")
    print(f"   Max lines per agent: {args.max_lines_per_agent}")
    print()

    # Identify trimmable lines
    try:
        trimmable = identify_trimmable_lines(
            session_file,
            exclude_types=exclude_types,
            preserve_recent=args.preserve_recent,
            max_lines_per_agent=args.max_lines_per_agent,
            verbose=args.verbose,
            content_threshold=args.content_threshold,
            preserve_head=args.preserve_head,
            preserve_tail=args.preserve_tail
        )
    except Exception as e:
        print(f"❌ Error analyzing session: {e}", file=sys.stderr)
        sys.exit(1)

    if not trimmable:
        print("✨ No lines identified for trimming")
        return

    print(f"📊 Identified {len(trimmable)} lines for trimming:")

    if args.verbose:
        # trimmable is list of (line_idx, rationale) tuples
        print(f"\n   All {len(trimmable)} lines with rationales:")
        for line_idx, rationale in trimmable:
            print(f"   Line {line_idx}: {rationale}")
    else:
        # trimmable is list of integers
        print(f"   Line indices: {trimmable[:10]}{'...' if len(trimmable) > 10 else ''}")
    print()

    if args.dry_run:
        print("🏃 Dry run mode - no changes made")
        return

    # Extract line indices (in case of verbose mode with rationales)
    if args.verbose:
        line_indices = [line_idx for line_idx, _ in trimmable]
    else:
        line_indices = trimmable

    # Determine output file
    output_dir = args.output_dir or session_file.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # Detect agent type from filename
    agent = detect_agent(session_file)
    if agent == "claude":
        # Generate new UUID for trimmed session
        new_uuid = str(uuid.uuid4())
        output_file = output_dir / f"{new_uuid}.jsonl"
    else:
        # Codex style
        timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        new_uuid = str(uuid.uuid4())
        output_file = output_dir / f"smart-trim-{timestamp}-{new_uuid[:8]}.jsonl"

    # Perform trimming
    stats = trim_lines(session_file, line_indices, output_file)

    # Add trim metadata to first line of output file
    import json
    from datetime import timezone

    # Build trim params dict
    trim_params = {
        "method": "smart-trim",
        "exclude_types": exclude_types,
        "content_threshold": args.content_threshold,
    }

    # Add preserve parameters that were used
    if args.preserve_head > 0:
        trim_params["preserve_head"] = args.preserve_head
    if args.preserve_tail is not None:
        trim_params["preserve_tail"] = args.preserve_tail
    else:
        trim_params["preserve_recent"] = args.preserve_recent

    metadata_fields = {
        "trim_metadata": {
            "parent_file": str(session_file.absolute()),
            "trimmed_at": datetime.datetime.now(timezone.utc).isoformat(),
            "trim_params": trim_params,
            "stats": {
                "num_lines_trimmed": stats['num_lines_trimmed'],
                "tokens_saved": stats['tokens_saved'],
            },
        }
    }

    # Read the file and modify first line
    with open(output_file, "r") as f:
        lines = f.readlines()

    if lines:
        try:
            # Parse first line and add metadata fields
            first_line_data = json.loads(lines[0])
            first_line_data.update(metadata_fields)
            lines[0] = json.dumps(first_line_data) + "\n"

            # Write back the modified file
            with open(output_file, "w") as f:
                f.writelines(lines)
        except json.JSONDecodeError:
            # If first line is malformed, just skip adding metadata
            pass

    print(f"✅ Smart trim complete!")
    print(f"   Lines trimmed: {stats['num_lines_trimmed']}")
    print(f"   Characters saved: {stats['chars_saved']:,}")
    print(f"   Tokens saved (est): ~{stats['tokens_saved']:,}")
    print()
    print(f"📄 Output: {output_file}")
    print(f"   Session ID: {output_file.stem}")


if __name__ == "__main__":
    main()
