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
from claude_code_tools.session_utils import build_rollover_prompt


def codex_continue(
    session_id_or_path: str,
    codex_home: Optional[str] = None,
    verbose: bool = False,
    custom_prompt: Optional[str] = None,
    precomputed_session_files: Optional[List[Path]] = None,
    quick_rollover: bool = False,
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
        quick_rollover: If True, just present lineage and wait for user input
            instead of running analysis to extract context (context rollover).
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

    # Step 2: Build prompt based on rollover type and number of session files
    # Codex-specific sub-agent instruction (more generic than Claude's)
    subagent_instruction = "parallel sub-agents (if available)"

    # Use shared prompt builder
    analysis_prompt = build_rollover_prompt(
        all_session_files=all_session_files,
        chronological_chain=chronological_chain,
        quick_rollover=quick_rollover,
        custom_prompt=custom_prompt,
        subagent_instruction=subagent_instruction,
    )

    # Step 3: Create new Codex session with analysis prompt and capture thread_id
    # For context rollover, use a smaller/cheaper model for the analysis step
    # Then resume with default model so user gets full capability
    from claude_code_tools.config import codex_rollover_model
    analysis_model = codex_rollover_model() if not quick_rollover else None

    if quick_rollover:
        print("Step 2: 🚀 Creating session with lineage info...")
    else:
        print("Step 2: 🤖 Creating session and analyzing history...")
        print(f"   Analyzing {len(all_session_files)} session file(s)...")
        print(f"   Using model: {analysis_model}")
    print()

    try:
        # Use codex exec --json with analysis prompt to create session and analyze
        # For context rollover: use smaller model for analysis (cheaper/faster)
        # For quick rollover: use default model (no --model flag)
        if analysis_model:
            cmd = ["codex", "exec", "--json", "--model", analysis_model, analysis_prompt]
        else:
            cmd = ["codex", "exec", "--json", analysis_prompt]

        if verbose:
            print(f"$ codex exec --json '<prompt>'")

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
    # Resume with default model (not the mini model used for analysis)
    from claude_code_tools.config import codex_default_model
    default_model = codex_default_model()

    print("Step 3: 🚀 Launching interactive Codex session...")
    print(f"   Session ID: {thread_id}")
    if default_model:
        print(f"   Model: {default_model}")
        resume_cmd = f'codex resume {shlex.quote(thread_id)} -c model="{default_model}"'
    else:
        print(f"   (Using codex default model)")
        resume_cmd = f"codex resume {shlex.quote(thread_id)}"
    print(f"$ {resume_cmd}")
    print()
    print("=" * 70)
    print()

    # Launch interactive Codex session
    exit_code = os.system(resume_cmd)
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
