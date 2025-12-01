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
    """
    print("🔄 Claude Continue - Transferring context to new session")
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
        print(f"ℹ️  Using {len(all_session_files)} precomputed session file(s)")
        print()
    else:
        # Step 1: Trace continuation lineage to find all parent sessions
        print("Step 1: Tracing session lineage...")

        from claude_code_tools.session_lineage import get_full_lineage_chain

        try:
            # Get full lineage chain (newest first, ending with original)
            lineage_chain = get_full_lineage_chain(old_session_file)

            if len(lineage_chain) > 1:
                print(f"✅ Found {len(lineage_chain)} session(s) in lineage:")
                for session_path, derivation_type in lineage_chain:
                    print(f"   - {session_path.name} ({derivation_type})")
                print()

            # Collect all session files in chronological order (oldest first)
            # lineage_chain is newest-first, so reverse it
            all_session_files = [path for path, _ in reversed(lineage_chain)]

        except Exception as e:
            print(f"⚠️  Warning: Could not trace lineage: {e}", file=sys.stderr)
            # Fall back to just the current session
            all_session_files = [old_session_file]

    # Step 2: Create new session with dummy message
    print("Step 2: Creating new Claude Code session...")

    try:
        # Run shell in interactive mode to load rc files (for shell functions like ccrja)
        # Use jq to add a marker prefix so we can reliably extract the session ID
        shell = os.environ.get('SHELL', '/bin/sh')
        cmd = f'{claude_cli} -p {shlex.quote("Hello")} --output-format json | jq -r \'"SESSION_ID:" + .session_id\''
        print(f"$ {cmd}")
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
            new_session_id = output.split(marker)[1].strip().split()[0]  # Get first token after marker
        else:
            raise ValueError(f"Could not find {marker} in output: {output}")
        print(f"✅ Created new session: {new_session_id}")
        print()
    except subprocess.CalledProcessError as e:
        print(f"❌ Error creating new session: {e}", file=sys.stderr)
        print(f"   stdout: {e.stdout}", file=sys.stderr)
        print(f"   stderr: {e.stderr}", file=sys.stderr)
        sys.exit(1)

    # Step 3: Have Claude analyze the session file(s) with parallel sub-agents
    print("Step 3: 🤖 Analyzing session history with parallel sub-agents...")

    # Build prompt based on number of session files
    if len(all_session_files) == 1:
        # Simple case: just the current session
        session_file = all_session_files[0]
        analysis_prompt = f"""There is a log of a past conversation with an AI agent in this JSONL session file: {session_file}

The file is in JSONL format (one JSON object per line). Each line represents a message in the conversation with fields like 'type' (user/assistant), 'message.content', etc. This format is easy to parse and understand.

Strategically use PARALLEL SUB-AGENTS to explore {session_file} (which may be very long) so that YOU have proper CONTEXT to continue the task that the agent was working on at the end of that chat.

DO NOT TRY TO READ {session_file} by YOURSELF! To save your own context, you must use parallel sub-agents, possibly to explore the beginning, middle, and end of that chat, so that you have sufficient context to continue the work where the agent left off.

If in this conversation you need more information about what happened during that previous conversation/session, you can again use a sub-agent(s) to explore {session_file}

When done exploring, state your understanding of the most recent task to me."""
    else:
        # Complex case: multiple sessions in the continuation chain
        file_list = "\n".join([f"{i+1}. {path}" for i, path in enumerate(all_session_files)])

        analysis_prompt = f"""There is a CHAIN of past conversations with an AI agent. The work was continued across multiple sessions as we ran out of context. Here are ALL the JSONL session files in CHRONOLOGICAL ORDER (oldest to newest):

{file_list}

Each file is in JSONL format (one JSON object per line). Each line represents a message with fields like 'type' (user/assistant), 'message.content', etc. This format is easy to parse and understand.

Each session was a continuation of the previous one. The LAST file ({all_session_files[-1]}) is the most recent session that ran out of context.

Strategically use PARALLEL SUB-AGENTS to explore ALL these files so that YOU have proper CONTEXT to continue the task. You should understand:
- The original task and requirements
- How the work progressed across sessions
- What was accomplished in each continuation
- The current state and what needs to be done next

DO NOT TRY TO READ these files by YOURSELF! To save your own context, you must use parallel sub-agents to explore these files. Consider:
- Exploring the beginning of the first file to understand the original task
- Exploring the end of each continuation to see what was accomplished
- Exploring the most recent file ({all_session_files[-1]}) thoroughly to understand the current state

If later in this conversation you need more information about what happened during those previous sessions, you can again use sub-agent(s) to explore the relevant files.

When done exploring, state your understanding of the full task history and the most recent work to me."""

    # Add directive about analyzing sessions
    analysis_prompt += """

IMPORTANT: Analyze ALL linked chat sessions unless the user explicitly instructs otherwise (e.g., "only analyze the most recent one", "skip the older sessions", etc.)."""

    # Append custom instructions if provided (with clear demarcation)
    if custom_prompt:
        analysis_prompt += f"""

=== USER INSTRUCTIONS (PRIORITIZE THESE) ===
{custom_prompt}
=== END USER INSTRUCTIONS ==="""

    print(f"   Analyzing {len(all_session_files)} session file(s)...")
    print()

    try:
        # Send analysis prompt - suppress output since we'll see it in interactive mode
        shell = os.environ.get('SHELL', '/bin/sh')
        cmd = f"{claude_cli} -p {shlex.quote(analysis_prompt)} --resume {shlex.quote(new_session_id)}"
        print(f"$ {claude_cli} -p '<analysis prompt>' --resume {new_session_id}")
        result = subprocess.run(
            [shell, "-i", "-c", cmd],
            capture_output=True,
            text=True,
            check=True
        )
        print("✅ Analysis complete - context transferred to new session")
        print()
    except subprocess.CalledProcessError as e:
        print(f"❌ Error during analysis: {e}", file=sys.stderr)
        if e.stderr:
            print(f"   {e.stderr}", file=sys.stderr)
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

    # Step 4: Resume in interactive mode - hand off to Claude
    print("🚀 Launching interactive Claude Code session...")
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
