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
import datetime
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import timezone
from pathlib import Path
from typing import Optional

from claude_code_tools.export_claude_session import export_session_programmatic
from claude_code_tools.session_lineage import get_continuation_lineage
from claude_code_tools.session_utils import get_claude_home, resolve_session_path


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

    # Resolve old session file path (needed for metadata)
    try:
        old_session_file = resolve_session_path(session_id_or_path, claude_home=claude_home)
    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)

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

    # Step 1.5: Get full continuation lineage (all parent sessions with exports)
    print("Step 1.5: Tracing continuation lineage...")

    try:
        lineage = get_continuation_lineage(
            old_session_file, export_missing=True
        )

        if lineage:
            print(f"✅ Found {len(lineage)} session(s) in continuation chain:")
            for node in lineage:
                derivation_label = f"({node.derivation_type})" if node.derivation_type else ""
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
        lineage = []

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

    # Step 3: Have Claude analyze the chat log(s) with parallel sub-agents
    print("Step 3: 🤖 Analyzing session history with parallel sub-agents...")

    # Build prompt based on number of exported files
    if len(all_exported_files) == 1:
        # Simple case: just the current session
        analysis_prompt = f"""There is a log of a past conversation with an AI agent in this file: {chat_log}. We were running out of context, so I exported the chat log to that file.

Strategically use PARALLEL SUB-AGENTS to explore {chat_log} (which may be very long) so that YOU have proper CONTEXT to continue the task that the agent was working on at the end of that chat.

DO NOT TRY TO READ {chat_log} by YOURSELF! To save your own context, you must use parallel sub-agents, possibly to explore the beginning, middle, and end of that chat, so that you have sufficient context to continue the work where the agent left off.

If in this conversation you need more information about what happened during that previous conversation/session, you can again use a sub-agent(s) to explore {chat_log}

When done exploring, state your understanding of the most recent task to me."""
    else:
        # Complex case: multiple sessions in the continuation chain
        file_list = "\n".join([f"{i+1}. {path}" for i, path in enumerate(all_exported_files)])

        analysis_prompt = f"""There is a CHAIN of past conversations with an AI agent. The work was continued across multiple sessions as we ran out of context. Here are ALL the exported chat logs in CHRONOLOGICAL ORDER (oldest to newest):

{file_list}

Each session was a continuation of the previous one. The LAST file ({all_exported_files[-1]}) is the most recent session that ran out of context.

Strategically use PARALLEL SUB-AGENTS to explore ALL these files so that YOU have proper CONTEXT to continue the task. You should understand:
- The original task and requirements
- How the work progressed across sessions
- What was accomplished in each continuation
- The current state and what needs to be done next

DO NOT TRY TO READ these files by YOURSELF! To save your own context, you must use parallel sub-agents to explore these files. Consider:
- Exploring the beginning of the first file to understand the original task
- Exploring the end of each continuation to see what was accomplished
- Exploring the most recent file ({all_exported_files[-1]}) thoroughly to understand the current state

If later in this conversation you need more information about what happened during those previous sessions, you can again use sub-agent(s) to explore the relevant files.

When done exploring, state your understanding of the full task history and the most recent work to me."""

    print(f"   Analyzing {len(all_exported_files)} exported session(s)...")
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
        encoded_path = str(cwd).replace("/", "-")
        new_session_file = home_dir / "projects" / encoded_path / f"{new_session_id}.jsonl"

        # Determine path format for exported chat log (relative if in cwd, absolute otherwise)
        try:
            chat_log_relative = chat_log.relative_to(cwd)
            chat_log_path = str(chat_log_relative)
        except ValueError:
            # Not in current directory, use absolute path
            chat_log_path = str(chat_log.absolute())

        # Create metadata
        metadata_fields = {
            "continue_metadata": {
                "parent_session_id": old_session_file.stem,
                "parent_session_file": str(old_session_file.absolute()),
                "exported_chat_log": chat_log_path,
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
