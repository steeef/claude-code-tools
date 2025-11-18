#!/usr/bin/env python3
"""
Continue a Claude Code session that's running out of context.

This tool helps you continue working when a Claude Code session is approaching
the context limit. It:
1. Exports the old session to a text file
2. Creates a new Claude Code session
3. Uses parallel sub-agents to analyze the old session
4. Hands off to interactive Claude Code to continue the task
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional

from claude_code_tools.export_claude_session import export_session_programmatic
from claude_code_tools.session_utils import resolve_session_path


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI escape codes from text."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def claude_continue(
    session_id_or_path: str,
    claude_home: Optional[str] = None,
    verbose: bool = False,
    claude_cli: str = "claude"
) -> None:
    """
    Continue a Claude Code session in a new session with full context.

    Args:
        session_id_or_path: Session to continue (file path or session ID)
        claude_home: Optional custom Claude home directory
        verbose: If True, show detailed progress
        claude_cli: Claude CLI command to use (default: "claude")
    """
    print("🔄 Claude Continue - Transferring context to new session")
    print()

    # Step 1: Export the old session to text file
    print("Step 1: Exporting old session to text file...")

    try:
        chat_log = export_session_programmatic(
            session_id_or_path,
            claude_home=claude_home,
            verbose=verbose
        )
        print(f"✅ Exported chat log to: {chat_log}")
        print()
    except Exception as e:
        print(f"❌ Error exporting session: {e}", file=sys.stderr)
        sys.exit(1)

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

    # Step 3: Have Claude analyze the chat log with parallel sub-agents
    print("Step 3: 🤖 Analyzing old session with parallel sub-agents...")

    analysis_prompt = f"""There is a log of a past conversation with an AI agent in this file: {chat_log}. We were running out of context, so I exported the chat log to that file.

Strategically use PARALLEL SUB-AGENTS to explore {chat_log} (which may be very long) so that YOU have proper CONTEXT to continue the task that the agent was working on at the end of that chat.

DO NOT TRY TO READ {chat_log} by YOURSELF! To save your own context, you must use parallel sub-agents, possibly to explore the beginning, middle, and end of that chat, so that you have sufficient context to continue the work where the agent left off.

If in this conversation you need more information about what happened during that previous conversation/session, you can again use a sub-agent(s) to explore {chat_log}

When done exploring, state your understanding of the most recent task to me."""

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

    # Step 4: Resume in interactive mode - hand off to Claude
    print("🚀 Launching interactive Claude Code session...")
    print(f"   Session ID: {new_session_id}")
    print(f"$ {claude_cli} --resume {new_session_id}")
    print()
    print("=" * 70)
    print()

    # Replace current process with interactive Claude Code via shell
    # (this handles both executables and shell functions)
    shell = os.environ.get('SHELL', '/bin/sh')
    cmd = f"{claude_cli} --resume {shlex.quote(new_session_id)}"
    os.execl(shell, shell, "-i", "-c", cmd)


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
  - Export your old session to a readable text file
  - Create a new Claude Code session
  - Use parallel sub-agents to understand the full context
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

    args = parser.parse_args()

    try:
        claude_continue(
            args.session,
            claude_home=args.claude_home,
            verbose=args.verbose,
            claude_cli=args.cli
        )
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
