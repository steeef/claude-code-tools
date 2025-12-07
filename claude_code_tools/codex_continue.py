#!/usr/bin/env python3
"""
Continue a Codex session that's running out of context.

This tool helps you continue working when a Codex session is approaching
the context limit. It:
1. Traces the session lineage to find all parent sessions
2. Creates a new Codex session with analysis prompt
3. Uses codex exec --json to run analysis programmatically
4. Hands off to interactive Codex to continue the task
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from claude_code_tools.export_codex_session import resolve_session_path


def codex_continue(
    session_id_or_path: str,
    codex_home: Optional[str] = None,
    verbose: bool = False,
    custom_prompt: Optional[str] = None,
    precomputed_session_files: Optional[List[Path]] = None,
) -> None:
    """
    Continue a Codex session in a new session with full context.

    Args:
        session_id_or_path: Session to continue (file path or session ID)
        codex_home: Optional custom Codex home directory
        verbose: If True, show detailed progress
        custom_prompt: Optional custom instructions for summarization
        precomputed_session_files: If provided, skip lineage tracing and use
            these JSONL session files directly. Used by continue_with_options()
            to avoid duplicate work.
    """
    print("🔄 Codex Rollover - Transferring context to fresh session")
    print()

    # Resolve session file path
    try:
        session_file = resolve_session_path(session_id_or_path, codex_home=codex_home)
    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Use precomputed session files if provided, otherwise trace lineage
    if precomputed_session_files is not None:
        # Skip lineage tracing - use precomputed data
        all_session_files = precomputed_session_files
        print(f"ℹ️  Using {len(all_session_files)} precomputed session file(s)")
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
            lineage_chain = get_full_lineage_chain(session_file)

            if len(lineage_chain) > 1:
                print(f"✅ Found {len(lineage_chain)} session(s) in lineage:")
                for session_path, derivation_type in lineage_chain:
                    print(f"   - {session_path.name} ({derivation_type})")
                print()

            # Collect all session files in chronological order (oldest first)
            # lineage_chain is newest-first, so reverse it
            # Keep both path and derivation_type for building file list
            chronological_chain = list(reversed(lineage_chain))
            all_session_files = [path for path, _ in chronological_chain]

        except Exception as e:
            print(f"⚠️  Warning: Could not trace lineage: {e}", file=sys.stderr)
            # Fall back to just the current session
            all_session_files = [session_file]
            chronological_chain = [(session_file, "original")]

    # Step 2: Build analysis prompt with lineage

    # Build prompt based on number of session files
    if len(all_session_files) == 1:
        # Simple case: just the current session
        session_file_path = all_session_files[0]
        analysis_prompt = f"""There is a log of a past conversation with an AI agent in this JSONL session file: {session_file_path}

The file is in JSONL format (one JSON object per line). Each line represents a message in the conversation with fields like 'type' (user/assistant), 'message.content', etc. This format is easy to parse and understand.

CAUTION: {session_file_path} may be very large. Strategically use parallel sub-agents if available, or use another strategy to efficiently read the file so your context window is not overloaded. For example, you could read specific sections (beginning, middle, end) rather than the entire file at once.

When done exploring, state your understanding of the most recent task to me."""
    else:
        # Complex case: multiple sessions in the chain
        # Build file list with derivation relationships
        def friendly_type(dtype: str) -> str:
            if dtype == "continued":
                return "rolled over"
            return dtype

        file_lines = []
        for i, (path, derivation_type) in enumerate(chronological_chain):
            if derivation_type == "original":
                file_lines.append(f"{i+1}. {path} (original)")
            else:
                parent_num = i  # previous item in 1-indexed
                friendly = friendly_type(derivation_type)
                file_lines.append(f"{i+1}. {path} ({friendly} from {parent_num})")
        file_list = "\n".join(file_lines)

        analysis_prompt = f"""There is a CHAIN of past conversations with an AI agent. The work progressed across multiple sessions as context filled up. Here are ALL the JSONL session files in CHRONOLOGICAL ORDER (oldest to newest):

{file_list}

**Terminology:**
- "trimmed" = Long messages were strategically truncated to free up context space. The full content is preserved in the parent session.
- "rolled over" = Work was handed off to a fresh session by summarizing the previous session's state.

Each file is in JSONL format (one JSON object per line). Each line represents a message with fields like 'type' (user/assistant), 'message.content', etc.

The LAST file ({all_session_files[-1]}) is the most recent session that ran out of context.

CAUTION: These files may be very large. Strategically use parallel sub-agents if available, or use another strategy to efficiently read the files so your context window is not overloaded. Consider:
- Reading the beginning of the first file to understand the original task
- Reading the end of each session to see what was accomplished
- Reading the most recent file ({all_session_files[-1]}) thoroughly to understand the current state

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

    # Step 3: Create new Codex session with analysis prompt and capture thread_id
    print("Step 2: 🤖 Creating session and analyzing history...")
    print(f"   Analyzing {len(all_session_files)} session file(s)...")
    print()

    try:
        # Use codex exec --json with analysis prompt to create session and analyze
        cmd = ["codex", "exec", "--json", analysis_prompt]

        if verbose:
            print(f"$ codex exec --json '<analysis prompt>'")

        # Run and capture JSON stream
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )

        # Parse JSON lines to extract thread_id from thread.started event
        thread_id = None
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                if event.get("type") == "thread.started":
                    thread_id = event.get("thread_id")
                    break
            except json.JSONDecodeError:
                continue

        if not thread_id:
            raise ValueError("Could not extract thread_id from codex exec output")

        print(f"✅ Session created and analysis complete: {thread_id}")
        print()

    except subprocess.CalledProcessError as e:
        print(f"❌ Error creating session: {e}", file=sys.stderr)
        if e.stderr:
            print(f"   {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Step 3: Resume in interactive mode - hand off to Codex
    print("Step 3: 🚀 Launching interactive Codex session...")
    print(f"   Session ID: {thread_id}")
    print(f"$ codex resume {thread_id}")
    print()
    print("=" * 70)
    print()

    # Launch interactive Codex session
    exit_code = os.system(f"codex resume {shlex.quote(thread_id)}")
    sys.exit(exit_code >> 8)  # Exit with codex's exit code


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Continue a Codex session that's running out of context",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example workflow:
  1. Exit your current Codex session when running low on context
  2. Note the session ID or file path
  3. Run: codex-continue <session-file-or-id>
  4. Codex will analyze the old session and continue the task

The tool will:
  - Trace the session lineage to find all parent sessions
  - Create a new Codex session
  - Analyze the JSONL session files directly
  - Launch interactive Codex to continue working
        """
    )
    parser.add_argument(
        "session",
        help="Session to continue (file path or session ID, supports partial matching)"
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
        help="Show detailed progress"
    )
    parser.add_argument(
        "--prompt",
        type=str,
        help="Custom instructions for summarization"
    )

    args = parser.parse_args()

    try:
        codex_continue(
            args.session,
            codex_home=args.codex_home,
            verbose=args.verbose,
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
