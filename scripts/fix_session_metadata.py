#!/usr/bin/env python3
"""
Fix session ID metadata in Claude and Codex session files.

This utility repairs session files where the sessionId in JSON content
doesn't match the filename UUID. This can happen with files that were
cloned or smart-trimmed before the fix in commit 13ac9ee.

Usage:
    fix-session-metadata --dry-run          # Report mismatches without fixing
    fix-session-metadata                     # Fix all mismatches
    fix-session-metadata --claude-home /path # Use specific Claude home
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

from claude_code_tools.session_utils import get_claude_home, get_codex_home
from claude_code_tools.trim_session import update_session_id_in_file


def extract_uuid_from_filename(filename: str, agent: str) -> Optional[str]:
    """
    Extract the UUID from a session filename.

    Args:
        filename: The filename (without path)
        agent: 'claude' or 'codex'

    Returns:
        The UUID string, or None if not extractable
    """
    if agent == "claude":
        # Claude format: <UUID>.jsonl
        if filename.endswith(".jsonl"):
            stem = filename[:-6]  # Remove .jsonl
            # Check if it looks like a UUID (contains hyphens, hex chars)
            if re.match(r"^[a-f0-9-]+$", stem, re.IGNORECASE):
                return stem
    elif agent == "codex":
        # Codex format: rollout-YYYY-MM-DDTHH-MM-SS-<UUID>.jsonl
        # or: smart-trim-YYYY-MM-DDTHH-MM-SS-<UUID>.jsonl
        match = re.search(r"-([a-f0-9-]{36})\.jsonl$", filename, re.IGNORECASE)
        if match:
            return match.group(1)
        # Also handle short UUID format: smart-trim-...-<UUID8>.jsonl
        match = re.search(r"-([a-f0-9]{8})\.jsonl$", filename, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def get_session_id_from_file(file_path: Path, agent: str) -> Optional[str]:
    """
    Extract the sessionId from the JSON content of a session file.

    Args:
        file_path: Path to the session file
        agent: 'claude' or 'codex'

    Returns:
        The sessionId from JSON, or None if not found
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 10:  # Only check first 10 lines
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if agent == "claude":
                    if "sessionId" in data:
                        return data["sessionId"]
                    # Skip non-session lines (file-history-snapshot, etc)
                elif agent == "codex":
                    if data.get("type") == "session_meta":
                        return data.get("payload", {}).get("id")
    except Exception:
        pass

    return None


def scan_directory(
    directory: Path,
    agent: str,
    dry_run: bool = True,
    verbose: bool = False,
) -> dict:
    """
    Scan a directory for session files with mismatched sessionIds.

    Args:
        directory: Directory to scan
        agent: 'claude' or 'codex'
        dry_run: If True, only report; if False, fix the files
        verbose: Print details for each file

    Returns:
        Dict with counts: total, mismatched, fixed, errors
    """
    stats = {"total": 0, "mismatched": 0, "fixed": 0, "errors": 0}

    if not directory.exists():
        return stats

    # Find all .jsonl files recursively
    for file_path in directory.rglob("*.jsonl"):
        # Skip non-session files
        if file_path.name.startswith("."):
            continue

        stats["total"] += 1

        # Extract UUID from filename
        filename_uuid = extract_uuid_from_filename(file_path.name, agent)
        if not filename_uuid:
            if verbose:
                print(f"  Skip (no UUID in name): {file_path.name}")
            continue

        # Get sessionId from JSON content
        json_session_id = get_session_id_from_file(file_path, agent)
        if not json_session_id:
            if verbose:
                print(f"  Skip (no sessionId in JSON): {file_path.name}")
            continue

        # Check for mismatch
        # For partial UUIDs (like smart-trim-...-abc12345.jsonl), check prefix
        if len(filename_uuid) == 8:
            # Short UUID - check if JSON ID starts with it
            is_match = json_session_id.startswith(filename_uuid)
        else:
            is_match = json_session_id == filename_uuid

        if not is_match:
            stats["mismatched"] += 1

            if dry_run:
                if verbose:
                    print(f"  MISMATCH: {file_path}")
                    print(f"    Filename UUID: {filename_uuid}")
                    print(f"    JSON sessionId: {json_session_id}")
            else:
                try:
                    update_session_id_in_file(file_path, filename_uuid, agent)
                    stats["fixed"] += 1
                    if verbose:
                        print(f"  FIXED: {file_path.name}")
                except Exception as e:
                    stats["errors"] += 1
                    print(f"  ERROR fixing {file_path}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Fix session ID metadata in Claude and Codex session files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  fix-session-metadata --dry-run          # Report mismatches without fixing
  fix-session-metadata                     # Fix all mismatches
  fix-session-metadata --claude-only       # Only fix Claude sessions
  fix-session-metadata --codex-only        # Only fix Codex sessions
""",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report mismatches without fixing them",
    )
    parser.add_argument(
        "--claude-home",
        type=str,
        default=None,
        help="Path to Claude home directory",
    )
    parser.add_argument(
        "--codex-home",
        type=str,
        default=None,
        help="Path to Codex home directory",
    )
    parser.add_argument(
        "--claude-only",
        action="store_true",
        help="Only scan Claude sessions",
    )
    parser.add_argument(
        "--codex-only",
        action="store_true",
        help="Only scan Codex sessions",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print details for each file",
    )

    args = parser.parse_args()

    # Determine which agents to scan
    scan_claude = not args.codex_only
    scan_codex = not args.claude_only

    if args.dry_run:
        print("DRY RUN - No files will be modified\n")
    else:
        print("FIXING session ID mismatches\n")

    total_stats = {"total": 0, "mismatched": 0, "fixed": 0, "errors": 0}

    # Scan Claude sessions
    if scan_claude:
        claude_home = get_claude_home(cli_arg=args.claude_home)
        claude_projects = claude_home / "projects"

        stats = scan_directory(
            claude_projects, "claude", dry_run=args.dry_run, verbose=args.verbose
        )

        print(f"Claude ({claude_home}):")
        print(f"  {stats['total']} files scanned, {stats['mismatched']} mismatched")
        if not args.dry_run:
            print(f"  {stats['fixed']} fixed, {stats['errors']} errors")

        for key in total_stats:
            total_stats[key] += stats[key]

    # Scan Codex sessions
    if scan_codex:
        codex_home = get_codex_home(cli_arg=args.codex_home)
        codex_sessions = codex_home / "sessions"

        stats = scan_directory(
            codex_sessions, "codex", dry_run=args.dry_run, verbose=args.verbose
        )

        print(f"Codex ({codex_home}):")
        print(f"  {stats['total']} files scanned, {stats['mismatched']} mismatched")
        if not args.dry_run:
            print(f"  {stats['fixed']} fixed, {stats['errors']} errors")

        for key in total_stats:
            total_stats[key] += stats[key]

    # Summary
    if scan_claude and scan_codex:
        print(f"\nTotal: {total_stats['total']} files, "
              f"{total_stats['mismatched']} mismatched")
        if not args.dry_run:
            print(f"  {total_stats['fixed']} fixed, {total_stats['errors']} errors")

    if args.dry_run and total_stats["mismatched"] > 0:
        print("\nRun without --dry-run to fix these files.")

    return 0 if total_stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
