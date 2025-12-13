#!/usr/bin/env python3
"""
Continue a Claude Code session that's running out of context.

This tool helps you continue working when a Claude Code session is approaching
the context limit. It:
1. Traces the session lineage to find all parent sessions
2. Creates a new Claude Code session
3. Uses parallel sub-agents to analyze the JSONL session files directly
4. Hands off to interactive Claude Code to continue the task
"""

import argparse
import datetime
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import timezone
from pathlib import Path
from typing import List, Optional

from claude_code_tools.session_utils import (
    get_claude_home,
    resolve_session_path,
    encode_claude_project_path,
    build_rollover_prompt,
    build_session_file_list,
)


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI escape codes from text."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def claude_continue(
    session_id_or_path: str,
    claude_home: Optional[str] = None,
    verbose: bool = False,
    claude_cli: str = "claude",
    custom_prompt: Optional[str] = None,
    precomputed_session_files: Optional[List[Path]] = None,
    quick_rollover: bool = False,
) -> None:
    """
    Continue a Claude Code session in a new session with full context.

    Args:
        session_id_or_path: Session to continue (file path or session ID)
        claude_home: Optional custom Claude home directory
        verbose: If True, show detailed progress
        claude_cli: Claude CLI command to use (default: "claude")
        custom_prompt: Optional custom instructions for summarization
        precomputed_session_files: If provided, skip lineage tracing and use
            these JSONL session files directly. Used by continue_with_options()
            to avoid duplicate work.
        quick_rollover: If True, just present lineage and wait for user input
            instead of running sub-agents to extract context (context rollover).
    """
    print("🔄 Claude Rollover - Transferring context to fresh session")
    print()

    # Resolve old session file path (needed for metadata)
    try:
        old_session_file = resolve_session_path(
            session_id_or_path, claude_home=claude_home
        )
    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Use precomputed session files if provided, otherwise trace lineage
    if precomputed_session_files is not None:
        # Skip lineage tracing - use precomputed data
        all_session_files = precomputed_session_files
        print(f"ℹ️  Using {len(all_session_files)} parent session file(s)")
        print()
        # Still need derivation types for the file list - trace from last file
        from claude_code_tools.session_lineage import get_full_lineage_chain
        try:
            lineage_chain = get_full_lineage_chain(all_session_files[-1])
            chronological_chain = list(reversed(lineage_chain))
        except Exception:
            # Fall back to assuming all are original (shouldn't happen)
            chronological_chain = [(p, "original") for p in all_session_files]
    else:
        # Step 1: Trace continuation lineage to find all parent sessions
        print("Step 1: Tracing session lineage...")

        from claude_code_tools.session_lineage import get_full_lineage_chain

        try:
            # Get full lineage chain (newest first, ending with original)
            lineage_chain = get_full_lineage_chain(old_session_file)

            if len(lineage_chain) > 1:
                print(f"✅ Found {len(lineage_chain)} session(s) in lineage:")
                # Use shared formatter (expects chronological order)
                chronological = list(reversed(lineage_chain))
                print(build_session_file_list(chronological))
                print()

            # Collect all session files in chronological order (oldest first)
            # lineage_chain is newest-first, so reverse it
            # Keep both path and derivation_type for building file list
            chronological_chain = list(reversed(lineage_chain))
            all_session_files = [path for path, _ in chronological_chain]

        except Exception as e:
            print(f"⚠️  Warning: Could not trace lineage: {e}", file=sys.stderr)
            # Fall back to just the current session
            all_session_files = [old_session_file]
            chronological_chain = [(old_session_file, "original")]

    # Step 2: Build prompt based on rollover type and number of session files
    # Get sub-agent model from config for Claude-specific instruction
    from claude_code_tools.config import claude_subagent_model
    subagent_model = claude_subagent_model()
    subagent_instruction = f"PARALLEL {subagent_model.upper()} SUB-AGENTS"

    # Use shared prompt builder
    analysis_prompt = build_rollover_prompt(
        all_session_files=all_session_files,
        chronological_chain=chronological_chain,
        quick_rollover=quick_rollover,
        custom_prompt=custom_prompt,
        subagent_instruction=subagent_instruction,
    )

    # Step 3: Create new session with analysis prompt and capture session ID
    if quick_rollover:
        print("Step 2: 🚀 Creating session with lineage info...")
    else:
        print("Step 2: 🤖 Creating session and analyzing history with sub-agents...")
        print(f"   Analyzing {len(all_session_files)} session file(s)...")
    print()

    try:
        # Run shell in interactive mode to load rc files (for shell functions like ccrja)
        # Use jq to add a marker prefix so we can reliably extract the session ID
        shell = os.environ.get('SHELL', '/bin/sh')
        cmd = f'{claude_cli} -p --no-session-persistence {shlex.quote(analysis_prompt)} --output-format json | jq -r \'"SESSION_ID:" + .session_id\''
        print(f"$ {claude_cli} -p '<analysis prompt>' --output-format json | jq ...")
        result = subprocess.run(
            [shell, "-i", "-c", cmd],
            capture_output=True,
            text=True,
            check=True
        )
        # Extract session ID from marker (ignore any shell prompt/title junk)
        output = result.stdout
        marker = "SESSION_ID:"
        if marker in output:
            new_session_id = output.split(marker)[1].strip().split()[0]
        else:
            raise ValueError(f"Could not find {marker} in output: {output}")
        print(f"✅ Session created and analysis complete: {new_session_id}")
        print()
    except subprocess.CalledProcessError as e:
        print(f"❌ Error creating session: {e}", file=sys.stderr)
        print(f"   stdout: {e.stdout}", file=sys.stderr)
        print(f"   stderr: {e.stderr}", file=sys.stderr)
        sys.exit(1)

    # Inject continue_metadata into new session file
    try:
        # Construct new session file path
        home_dir = get_claude_home(claude_home)
        cwd = Path.cwd()
        encoded_path = encode_claude_project_path(str(cwd))
        new_session_file = home_dir / "projects" / encoded_path / f"{new_session_id}.jsonl"

        # Create metadata (no longer storing exported_chat_log since we use JSONL directly)
        metadata_fields = {
            "continue_metadata": {
                "parent_session_id": old_session_file.stem,
                "parent_session_file": str(old_session_file.absolute()),
                "continued_at": datetime.datetime.now(timezone.utc).isoformat(),
            }
        }

        # Read the new session file and modify first line
        if new_session_file.exists():
            with open(new_session_file, "r") as f:
                lines = f.readlines()

            if lines:
                try:
                    # Parse first line and add metadata fields
                    first_line_data = json.loads(lines[0])
                    first_line_data.update(metadata_fields)
                    lines[0] = json.dumps(first_line_data) + "\n"

                    # Write back the modified file
                    with open(new_session_file, "w") as f:
                        f.writelines(lines)

                    if verbose:
                        print(f"✅ Added continue_metadata to new session")
                        print()
                except json.JSONDecodeError:
                    # If first line is malformed, skip adding metadata
                    if verbose:
                        print(f"⚠️  Could not add metadata (first line malformed)", file=sys.stderr)
    except Exception as e:
        # Don't fail the whole operation if metadata injection fails
        if verbose:
            print(f"⚠️  Could not add continue_metadata: {e}", file=sys.stderr)

    # Step 3: Resume in interactive mode - hand off to Claude
    print("Step 3: 🚀 Launching interactive Claude Code session...")
    print(f"   Session ID: {new_session_id}")
    print(f"$ {claude_cli} --resume {new_session_id}")
    print()
    print("=" * 70)
    print()

    # Launch interactive Claude Code session
    # Run through interactive shell to handle shell functions, os.system handles TTY properly
    shell = os.environ.get('SHELL', '/bin/sh')
    cmd = f"{claude_cli} --resume {shlex.quote(new_session_id)}"
    exit_code = os.system(f"{shell} -i -c {shlex.quote(cmd)}")
    sys.exit(exit_code >> 8)  # Exit with claude's exit code


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Continue a Claude Code session that's running out of context",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example workflow:
  1. Exit your current Claude Code session when running low on context
  2. Note the session ID (shown in the prompt or via get-current-session)
  3. Run: claude-continue <session-id>
  4. Claude will analyze the old session and continue the task

The tool will:
  - Trace the session lineage to find all parent sessions
  - Create a new Claude Code session
  - Use parallel sub-agents to analyze the JSONL session files directly
  - Launch interactive Claude Code to continue working
        """
    )
    parser.add_argument(
        "session",
        help="Session to continue (file path or session ID, supports partial matching)"
    )
    parser.add_argument(
        "--claude-home",
        type=str,
        help="Path to Claude home directory (default: ~/.claude or $CLAUDE_CONFIG_DIR)"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed progress"
    )
    parser.add_argument(
        "--cli",
        type=str,
        default="claude",
        help="Claude CLI command to use (default: claude)"
    )
    parser.add_argument(
        "--prompt",
        type=str,
        help="Custom instructions for summarization"
    )

    args = parser.parse_args()

    try:
        claude_continue(
            args.session,
            claude_home=args.claude_home,
            verbose=args.verbose,
            claude_cli=args.cli,
            custom_prompt=args.prompt
        )
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
