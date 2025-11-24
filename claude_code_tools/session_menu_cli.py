#!/usr/bin/env python3
"""
Interactive session menu CLI tool.

Usage:
    session-menu <session_id_or_path> [options]

This tool provides an interactive menu for managing Claude Code and
Codex sessions. It can accept either a session ID or a full file path,
auto-detecting the agent type.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

from claude_code_tools.session_menu import (
    show_action_menu,
    prompt_suppress_options,
)
from claude_code_tools.session_utils import (
    get_claude_home,
    get_codex_home,
    detect_agent_from_path,
    extract_cwd_from_session,
    extract_git_branch_claude,
    extract_session_metadata_codex,
    find_session_file,
    is_malformed_session,
)


def is_sidechain_session(session_file: Path) -> bool:
    """Check if session is a sidechain (sub-agent) session."""
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "file-history-snapshot":
                        metadata = entry.get("metadata", {})
                        return metadata.get("is_sidechain", False)
                except json.JSONDecodeError:
                    continue
    except (OSError, IOError):
        pass
    return False


def execute_action(
    action: str,
    agent: str,
    session_file: Path,
    project_path: str,
    claude_home: Optional[str] = None,
    codex_home: Optional[str] = None,
) -> None:
    """
    Execute the selected action by delegating to appropriate tool.

    Args:
        action: The action to execute
        agent: 'claude' or 'codex'
        session_file: Path to session file
        project_path: Project directory path
        claude_home: Optional custom Claude home
        codex_home: Optional custom Codex home
    """
    if action == "path":
        print(f"\nSession file path:")
        print(f"{session_file}")

    elif action == "copy":
        if agent == "claude":
            from claude_code_tools.find_claude_session import (
                copy_session_file,
            )
        else:
            from claude_code_tools.find_codex_session import (
                copy_session_file,
            )
        copy_session_file(str(session_file))

    elif action == "export":
        if agent == "claude":
            from claude_code_tools.find_claude_session import (
                handle_export_session,
            )
        else:
            from claude_code_tools.find_codex_session import (
                handle_export_session,
            )
        handle_export_session(str(session_file))

    elif action == "clone":
        session_id = session_file.stem
        if agent == "claude":
            from claude_code_tools.find_claude_session import clone_session
            clone_session(
                session_id, project_path, shell_mode=False, claude_home=claude_home
            )
        else:
            from claude_code_tools.find_codex_session import clone_session
            clone_session(
                str(session_file),
                session_id,
                project_path,
                shell_mode=False,
                codex_home=codex_home
            )

    elif action == "resume":
        session_id = session_file.stem
        if agent == "claude":
            from claude_code_tools.find_claude_session import resume_session
            resume_session(
                session_id, project_path, shell_mode=False, claude_home=claude_home
            )
        else:
            from claude_code_tools.find_codex_session import resume_session
            resume_session(str(session_file), shell_mode=False)

    elif action == "suppress_resume":
        result = prompt_suppress_options()
        if result is None:
            return
        tools, threshold, trim_assistant = result

        if agent == "claude":
            from claude_code_tools.find_claude_session import (
                handle_suppress_resume_claude,
            )
            session_id = session_file.stem
            handle_suppress_resume_claude(
                session_id,
                project_path,
                tools,
                threshold,
                trim_assistant,
                claude_home,
            )
        else:
            from claude_code_tools.find_codex_session import (
                handle_suppress_resume_codex,
            )
            handle_suppress_resume_codex(
                str(session_file),
                tools,
                threshold,
                trim_assistant,
                codex_home,
            )

    elif action == "smart_trim_resume":
        if agent == "claude":
            from claude_code_tools.find_claude_session import (
                handle_smart_trim_resume_claude,
            )
            session_id = session_file.stem
            handle_smart_trim_resume_claude(
                session_id, project_path, claude_home
            )
        else:
            from claude_code_tools.find_codex_session import (
                handle_smart_trim_resume_codex,
            )
            handle_smart_trim_resume_codex(str(session_file), codex_home)

    elif action == "continue":
        # Continue with context in fresh session
        from claude_code_tools.session_utils import execute_continue_action
        execute_continue_action(
            str(session_file),
            agent,
            claude_home=claude_home,
            codex_home=codex_home
        )


def main():
    """Main entry point for session-menu CLI."""
    parser = argparse.ArgumentParser(
        description="Interactive menu for Claude/Codex sessions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  session-menu abc123def456                    # By session ID
  session-menu ~/.claude/projects/foo/session.jsonl  # By file path
  session-menu abc123 --agent claude           # Force agent type
        """,
    )
    parser.add_argument(
        "session_id_or_path",
        help="Session ID or full path to session file",
    )
    parser.add_argument(
        "--agent",
        choices=["claude", "codex"],
        help="Force agent type (auto-detected if not specified)",
    )
    parser.add_argument(
        "--claude-home",
        help="Custom Claude home directory (default: ~/.claude)",
    )
    parser.add_argument(
        "--codex-home",
        help="Custom Codex home directory (default: ~/.codex)",
    )
    parser.add_argument(
        "--shell",
        action="store_true",
        help="Shell mode for persistent directory changes",
    )

    args = parser.parse_args()

    # Determine if input is a file path or session ID
    input_path = Path(args.session_id_or_path).expanduser()

    if input_path.exists() and input_path.is_file():
        # Input is a file path
        agent = args.agent or detect_agent_from_path(input_path)
        if not agent:
            print(
                "Error: Could not auto-detect agent type. "
                "Use --agent to specify.",
                file=sys.stderr,
            )
            sys.exit(1)

        session_file = input_path
        session_id = session_file.stem

        # Extract project info based on agent type
        if agent == "claude":
            git_branch = extract_git_branch_claude(session_file)
            # Extract actual cwd from session file
            actual_cwd = extract_cwd_from_session(session_file)
            if actual_cwd:
                project_path = actual_cwd
                project_name = Path(actual_cwd).name
            else:
                # Cannot extract cwd - this shouldn't happen for valid Claude sessions
                print(
                    f"Error: Could not extract working directory from session file: {session_file}",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            metadata = extract_session_metadata_codex(session_file)
            if metadata:
                project_path = metadata.get("cwd", "")
                project_name = Path(project_path).name or "unknown"
                git_branch = metadata.get("branch")
            else:
                print(
                    "Error: Could not extract metadata from session file.",
                    file=sys.stderr,
                )
                sys.exit(1)

    else:
        # Input is a session ID - search for it
        session_id = args.session_id_or_path
        result = find_session_file(
            session_id, args.claude_home, args.codex_home
        )

        if not result:
            print(
                f"Error: Session '{session_id}' not found in Claude or "
                f"Codex homes.",
                file=sys.stderr,
            )
            sys.exit(1)

        agent, session_file, project_path, git_branch = result

        # Override agent if specified
        if args.agent and args.agent != agent:
            print(
                f"Warning: Found session in {agent} but --agent {args.agent} "
                f"specified. Using {agent}.",
                file=sys.stderr,
            )

    # Derive project name from project path
    project_name = Path(project_path).name if project_path else "unknown"

    # Check if sidechain
    is_sidechain = is_sidechain_session(session_file)

    # Show action menu
    action = show_action_menu(
        session_id=session_id,
        agent=agent,
        project_name=project_name,
        git_branch=git_branch,
        is_sidechain=is_sidechain,
        stderr_mode=args.shell,
    )

    if action:
        execute_action(
            action,
            agent,
            session_file,
            project_path,
            args.claude_home,
            args.codex_home,
        )


if __name__ == "__main__":
    main()
