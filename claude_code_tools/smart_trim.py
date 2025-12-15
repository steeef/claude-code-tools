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

from claude_code_tools.smart_trim_core import identify_trimmable_lines_cli, SMART_TRIM_THRESHOLD
from claude_code_tools.trim_session import detect_agent, inject_lineage_into_first_user_message
from claude_code_tools.session_utils import get_claude_home, get_session_uuid, resolve_session_path


def trim_lines(
    input_file: Path,
    line_indices: List[int],
    output_file: Path,
    parent_file: Optional[str] = None,
    descriptions: Optional[dict] = None,
) -> dict:
    """
    Replace content within specified lines with placeholders.

    IMPORTANT: Never delete or replace entire message lines - this breaks the
    conversation structure that the Anthropic API requires. Instead, replace
    CONTENT fields (text, tool results, etc.) within messages.

    Args:
        input_file: Input session file
        line_indices: Line numbers to trim (0-indexed)
        output_file: Output file path
        parent_file: Path to parent session file (for truncation references)
        descriptions: Optional dict mapping line indices to short descriptions
            of what the content contains (with file paths when relevant)

    Returns:
        Stats dict with num_lines_trimmed and chars_saved
    """
    # Use input_file as parent_file if not provided
    if parent_file is None:
        parent_file = str(input_file.absolute())

    # Initialize descriptions dict if not provided
    if descriptions is None:
        descriptions = {}

    def truncate_content(content: str, content_type: str, line_num: int) -> str:
        """Truncate content to threshold and add placeholder notice."""
        if len(content) <= SMART_TRIM_THRESHOLD:
            return content  # Don't truncate short content

        desc = descriptions.get(idx, "")
        truncated = content[:SMART_TRIM_THRESHOLD]

        # Build structured truncation notice
        lines = []
        if desc:
            lines.append(f"Summary of truncated content: {desc}")
        lines.append(
            f"First {SMART_TRIM_THRESHOLD} chars: {truncated}... [truncated]"
        )
        lines.append(
            f"See line {line_num} of {parent_file} for full content "
            f"(original was {len(content):,} chars)."
        )
        result = "\n".join(lines)

        # Accept any truncation that saves space
        # (overall 300 token threshold is checked after all truncations)
        if len(result) >= len(content):
            return content

        return result

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

                # Convert 0-indexed to 1-indexed for display
                line_num = idx + 1

                # Determine message type and replace content appropriately
                msg_type = data.get("type", "")
                trimmed = False

                # Claude Code format
                if msg_type == "assistant":
                    # Truncate text content in assistant messages
                    message = data.get("message", {})
                    content = message.get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text = item.get("text", "")
                                if text and len(text) >= SMART_TRIM_THRESHOLD:
                                    item["text"] = truncate_content(
                                        text, "content", line_num
                                    )
                                    trimmed = True

                elif msg_type == "user":
                    # Truncate tool result content
                    message = data.get("message", {})
                    content = message.get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "tool_result":
                                result_content = item.get("content", "")
                                if isinstance(result_content, str) and len(result_content) >= SMART_TRIM_THRESHOLD:
                                    item["content"] = truncate_content(
                                        result_content, "tool result", line_num
                                    )
                                    trimmed = True
                                elif isinstance(result_content, list):
                                    # Handle list format - convert to string first
                                    combined = "".join(str(c) for c in result_content)
                                    if len(combined) >= SMART_TRIM_THRESHOLD:
                                        item["content"] = truncate_content(
                                            combined, "tool result", line_num
                                        )
                                        trimmed = True

                # Codex format (response_item with payload)
                elif msg_type == "response_item":
                    payload = data.get("payload", {})
                    payload_type = payload.get("type", "")

                    if payload_type == "message":
                        # Truncate message text content
                        content = payload.get("content", [])
                        if isinstance(content, list):
                            for item in content:
                                if isinstance(item, dict):
                                    text = item.get("text", "")
                                    if text and len(text) >= SMART_TRIM_THRESHOLD:
                                        item["text"] = truncate_content(
                                            text, "content", line_num
                                        )
                                        trimmed = True

                    elif payload_type == "function_call_output":
                        # Truncate function output
                        output = payload.get("output", "")
                        if output and len(str(output)) >= SMART_TRIM_THRESHOLD:
                            payload["output"] = truncate_content(
                                str(output), "function output", line_num
                            )
                            trimmed = True

                # Codex old format
                elif msg_type == "message":
                    content = data.get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict):
                                text = item.get("text", "")
                                if text and len(text) >= SMART_TRIM_THRESHOLD:
                                    item["text"] = truncate_content(
                                        text, "content", line_num
                                    )
                                    trimmed = True

                elif msg_type == "function_call_output":
                    output = data.get("output", "")
                    if output and len(str(output)) >= SMART_TRIM_THRESHOLD:
                        data["output"] = truncate_content(
                            str(output), "function output", line_num
                        )
                        trimmed = True

                if trimmed:
                    # Write modified line
                    new_line = json.dumps(data) + "\n"
                    saved = original_len - len(new_line)
                    # Only count as trimmed if we actually saved space
                    if saved > 0:
                        chars_saved += saved
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
        help="Always preserve last N messages (default: 10)"
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

    # Detect agent type for CLI
    agent = detect_agent(session_file)
    cli_type = "codex" if agent == "codex" else "claude"

    print(f"🔍 Analyzing session: {session_file.name}")
    print(f"   Excluding types: {', '.join(exclude_types)}")
    print(f"   Preserving recent: {args.preserve_recent} messages")
    print(f"   Using CLI: {cli_type}")
    print()

    # Identify trimmable lines using CLI
    try:
        trimmable = identify_trimmable_lines_cli(
            session_file,
            exclude_types=exclude_types,
            preserve_recent=args.preserve_recent,
            content_threshold=args.content_threshold,
            cli_type=cli_type,
        )
    except Exception as e:
        print(f"❌ Error analyzing session: {e}", file=sys.stderr)
        sys.exit(1)

    if not trimmable:
        print("✨ No lines identified for trimming")
        return

    print(f"📊 Identified {len(trimmable)} lines for trimming:")

    # Build descriptions dict - trimmable is list of (line_idx, rationale, description) tuples
    descriptions = {}
    print(f"\n   All {len(trimmable)} lines with rationales:")
    for item in trimmable:
        line_idx = item[0]
        rationale = item[1]
        description = item[2] if len(item) > 2 else ""
        print(f"   Line {line_idx}: {rationale}")
        if description:
            print(f"      → {description}")
            descriptions[line_idx] = description
    print()

    if args.dry_run:
        print("🏃 Dry run mode - no changes made")
        return

    # Extract line indices from tuples
    line_indices = [item[0] for item in trimmable]

    # Determine output file
    # Use agent type already detected earlier
    if agent == "claude":
        # Claude: output in same directory or specified output_dir
        output_dir = args.output_dir or session_file.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        new_uuid = str(uuid.uuid4())
        output_file = output_dir / f"{new_uuid}.jsonl"
    else:
        # Codex: new session goes in today's date folder (YYYY/MM/DD)
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y-%m-%dT%H-%M-%S")
        date_path = now.strftime("%Y/%m/%d")
        new_uuid = str(uuid.uuid4())

        if args.output_dir:
            output_dir = args.output_dir / date_path
        else:
            # Find sessions root by going up from input file (sessions/YYYY/MM/DD/file.jsonl)
            sessions_root = session_file.parent.parent.parent.parent
            output_dir = sessions_root / date_path

        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"rollout-{timestamp}-{new_uuid}.jsonl"

    # Perform trimming (pass descriptions for truncation summaries)
    stats = trim_lines(session_file, line_indices, output_file, descriptions=descriptions)

    # Add trim metadata to first line of output file
    import json
    from datetime import timezone

    # Build trim params dict
    trim_params = {
        "method": "smart-trim",
        "exclude_types": exclude_types,
        "content_threshold": args.content_threshold,
        "preserve_recent": args.preserve_recent,
        "cli_type": cli_type,
    }

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

    # Inject parent session lineage into first user message
    inject_lineage_into_first_user_message(output_file, session_file, agent)

    # Update sessionId in all lines to match the new filename UUID
    from claude_code_tools.trim_session import update_session_id_in_file
    update_session_id_in_file(output_file, new_uuid, agent)

    print(f"✅ Smart trim complete!")
    print(f"   Lines trimmed: {stats['num_lines_trimmed']}")
    print(f"   Characters saved: {stats['chars_saved']:,}")
    print(f"   Tokens saved (est): ~{stats['tokens_saved']:,}")
    print()
    print(f"📄 Output: {output_file}")
    print(f"   Session ID: {get_session_uuid(output_file.name)}")


if __name__ == "__main__":
    main()
