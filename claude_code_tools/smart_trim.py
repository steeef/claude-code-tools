#!/usr/bin/env python3
"""Smart trim: LLM-powered intelligent session trimming."""

import argparse
import datetime
import json
import sys
import uuid
from pathlib import Path
from typing import List

from claude_code_tools.smart_trim_core import identify_trimmable_lines
from claude_code_tools.trim_session import detect_agent


def trim_lines(input_file: Path, line_indices: List[int], output_file: Path) -> dict:
    """
    Replace specified lines with placeholders.

    Args:
        input_file: Input session file
        line_indices: Line numbers to trim
        output_file: Output file path

    Returns:
        Stats dict with num_lines_trimmed and chars_saved
    """
    with open(input_file, 'r') as f:
        lines = f.readlines()

    chars_saved = 0
    trimmed_count = 0

    # Replace lines with placeholders
    for idx in sorted(line_indices):
        if 0 <= idx < len(lines):
            original_len = len(lines[idx])
            placeholder = f'{{"trimmed_line": true, "original_length": {original_len}, "line_number": {idx}}}\n'
            chars_saved += original_len - len(placeholder)
            lines[idx] = placeholder
            trimmed_count += 1

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
        type=Path,
        help="Session JSONL file to analyze"
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

    args = parser.parse_args()

    if not args.session_file.exists():
        print(f"Error: File not found: {args.session_file}", file=sys.stderr)
        sys.exit(1)

    # Parse exclude types
    exclude_types = [t.strip() for t in args.exclude_types.split(",")]

    print(f"🔍 Analyzing session: {args.session_file.name}")
    print(f"   Excluding types: {', '.join(exclude_types)}")
    print(f"   Preserving recent: {args.preserve_recent} messages")
    print(f"   Max lines per agent: {args.max_lines_per_agent}")
    print()

    # Identify trimmable lines
    try:
        trimmable = identify_trimmable_lines(
            args.session_file,
            exclude_types=exclude_types,
            preserve_recent=args.preserve_recent,
            max_lines_per_agent=args.max_lines_per_agent,
            verbose=args.verbose,
            content_threshold=args.content_threshold
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
    output_dir = args.output_dir or args.session_file.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # Detect agent type from filename
    agent = detect_agent(args.session_file)
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
    stats = trim_lines(args.session_file, line_indices, output_file)

    print(f"✅ Smart trim complete!")
    print(f"   Lines trimmed: {stats['num_lines_trimmed']}")
    print(f"   Characters saved: {stats['chars_saved']:,}")
    print(f"   Tokens saved (est): ~{stats['tokens_saved']:,}")
    print()
    print(f"📄 Output: {output_file}")
    print(f"   Session ID: {output_file.stem}")


if __name__ == "__main__":
    main()
