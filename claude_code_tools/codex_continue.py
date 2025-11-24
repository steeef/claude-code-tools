#!/usr/bin/env python3
"""
Continue a Codex session that's running out of context.

This tool helps you continue working when a Codex session is approaching
the context limit. It:
1. Exports the old session to a text file
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
    precomputed_exports: Optional[List[Path]] = None,
) -> None:
    """
    Continue a Codex session in a new session with full context.

    Args:
        session_id_or_path: Session to continue (file path or session ID)
        codex_home: Optional custom Codex home directory
        verbose: If True, show detailed progress
        custom_prompt: Optional custom instructions for summarization
        precomputed_exports: If provided, skip export/lineage steps and use
            these exported files directly. Used by continue_with_options()
            to avoid duplicate work.
    """
    print("🔄 Codex Continue - Transferring context to new session")
    print()

    # Resolve session file path
    try:
        session_file = resolve_session_path(session_id_or_path, codex_home=codex_home)
    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Use precomputed exports if provided, otherwise do export/lineage
    if precomputed_exports is not None:
        # Skip export and lineage - use precomputed data
        all_exported_files = precomputed_exports
        chat_log = all_exported_files[-1] if all_exported_files else None
        print(f"ℹ️  Using {len(all_exported_files)} precomputed export(s)")
        print()
    else:
        # Step 1: Export the old session to text file
        print("Step 1: Exporting old session to text file...")

        from claude_code_tools.export_codex_session import (
            export_session_programmatic,
        )

        try:
            chat_log = export_session_programmatic(
                str(session_file),
                codex_home=codex_home,
                verbose=verbose
            )
            print(f"✅ Exported chat log to: {chat_log}")
            print()
        except Exception as e:
            print(f"❌ Error exporting session: {e}", file=sys.stderr)
            sys.exit(1)

        # Step 1.5: Get full continuation lineage (all parent sessions with exports)
        print("Step 1.5: Tracing continuation lineage...")

        from claude_code_tools.session_lineage import get_continuation_lineage

        try:
            lineage = get_continuation_lineage(
                session_file, export_missing=True
            )

            if lineage:
                print(f"✅ Found {len(lineage)} session(s) in continuation chain:")
                for node in lineage:
                    derivation_label = (
                        f"({node.derivation_type})" if node.derivation_type else ""
                    )
                    print(f"   - {node.session_file.name} {derivation_label}")
                    if node.exported_file:
                        print(f"     Export: {node.exported_file}")
                print()

            # Collect all exported files in chronological order
            all_exported_files = [
                node.exported_file for node in lineage if node.exported_file
            ]
            # Add the current session's export at the end
            all_exported_files.append(chat_log)

        except Exception as e:
            print(f"⚠️  Warning: Could not trace lineage: {e}", file=sys.stderr)
            # Fall back to just the current session
            all_exported_files = [chat_log]

    # Step 2: Build analysis prompt
    print("Step 2: Preparing analysis prompt...")

    # Build prompt based on number of exported files
    if len(all_exported_files) == 1:
        # Simple case: just the current session
        analysis_prompt = f"""There is a log of a past conversation with an AI agent in this file: {chat_log}. We were running out of context, so I exported the chat log to that file.

CAUTION: {chat_log} may be very large. Strategically use parallel sub-agents if available, or use another strategy to efficiently read the file so your context window is not overloaded. For example, you could read specific sections (beginning, middle, end) rather than the entire file at once.

When done exploring, state your understanding of the most recent task to me."""
    else:
        # Complex case: multiple sessions in the continuation chain
        file_list = "\n".join([f"{i+1}. {path}" for i, path in enumerate(all_exported_files)])

        analysis_prompt = f"""There is a CHAIN of past conversations with an AI agent. The work was continued across multiple sessions as we ran out of context. Here are ALL the exported chat logs in CHRONOLOGICAL ORDER (oldest to newest):

{file_list}

Each session was a continuation of the previous one. The LAST file ({all_exported_files[-1]}) is the most recent session that ran out of context.

CAUTION: These files may be very large. Strategically use parallel sub-agents if available, or use another strategy to efficiently read the files so your context window is not overloaded. Consider:
- Reading the beginning of the first file to understand the original task
- Reading the end of each continuation to see what was accomplished
- Reading the most recent file ({all_exported_files[-1]}) thoroughly to understand the current state

When done exploring, state your understanding of the full task history and the most recent work to me."""

    # Append custom instructions if provided
    if custom_prompt:
        analysis_prompt += f"""

Below are some special instructions from the user. Prioritize these in combination with the above instructions:

{custom_prompt}"""

    print(f"   Analyzing {len(all_exported_files)} exported session(s)...")
    print()

    # Step 3: Create new Codex session with simple prompt
    print("Step 3: Creating new Codex session...")

    try:
        # Use codex exec --json with simple hello to create session
        cmd = ["codex", "exec", "--json", "Hello"]

        if verbose:
            print(f"$ {' '.join(shlex.quote(arg) for arg in cmd)}")

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

        print(f"✅ Created new session: {thread_id}")
        print()

    except subprocess.CalledProcessError as e:
        print(f"❌ Error creating new session: {e}", file=sys.stderr)
        if e.stderr:
            print(f"   {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Step 4: Send analysis prompt to the new session
    print("Step 4: 🤖 Analyzing session history...")

    try:
        # Use codex exec resume with analysis prompt
        cmd = [
            "codex", "exec", "resume", thread_id,
            analysis_prompt
        ]

        if verbose:
            print(f"$ codex exec resume {thread_id} '<analysis prompt>'")

        # Run analysis - suppress output since we'll see it in interactive mode
        result = subprocess.run(
            cmd,
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
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Step 5: Resume in interactive mode - hand off to Codex
    print("🚀 Launching interactive Codex session...")
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
  - Export your old session to a readable text file
  - Create a new Codex session
  - Analyze the full context programmatically
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
