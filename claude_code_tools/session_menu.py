"""
Interactive menu system for session management.

This module provides reusable menu functions for displaying and
handling user interactions with Claude/Codex sessions. Extracted
from find-session tools to eliminate code duplication and enable
future menu library upgrades.
"""

from typing import Optional, Tuple


def show_resume_submenu(stderr_mode: bool = False) -> Optional[str]:
    """
    Show resume options submenu.

    Args:
        stderr_mode: If True, prompt via stderr for shell mode

    Returns:
        Action choice: 'resume', 'suppress_resume', 'smart_trim_resume',
        or None if cancelled
    """
    print(f"\nResume options:")
    print("1. Default, just resume as is (default)")
    print("2. Trim session (tool results + assistant messages) and resume")
    print("3. Smart trim (EXPERIMENTAL - using Claude SDK agents) and resume")
    print()

    try:
        choice = input("Enter choice [1-3] (or Enter for 1): ").strip()
        if not choice or choice == "1":
            return "resume"
        elif choice == "2":
            return "suppress_resume"
        elif choice == "3":
            return "smart_trim_resume"
        else:
            print("Invalid choice.")
            return None
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return None


def prompt_suppress_options(
    stderr_mode: bool = False,
) -> Optional[Tuple[Optional[str], int, Optional[int]]]:
    """
    Prompt user for suppress-tool-results/trim options.

    Args:
        stderr_mode: If True, prompt via stderr for shell mode

    Returns:
        Tuple of (tools, threshold, trim_assistant_messages) or None
        if cancelled
    """
    print(f"\nTrim session options:")
    print(
        "Enter tool names to trim (comma-separated, e.g., 'bash,read,edit')"
    )
    print("Or press Enter to trim all tools:")

    try:
        tools_input = input("Tools (or Enter for all): ").strip()
        tools = tools_input if tools_input else None

        print(f"\nEnter length threshold in characters (default: 500):")
        threshold_input = input("Threshold (or Enter for 500): ").strip()
        threshold = int(threshold_input) if threshold_input else 500

        print(f"\nTrim assistant messages (optional):")
        print(
            "  • Positive number (e.g., 10): Trim first 10 messages "
            "exceeding threshold"
        )
        print(
            "  • Negative number (e.g., -5): Trim all except last 5 "
            "messages exceeding threshold"
        )
        print("  • Press Enter to skip (no assistant message trimming)")
        assistant_input = input(
            "Assistant messages (or Enter to skip): "
        ).strip()

        trim_assistant = None
        if assistant_input:
            trim_assistant = int(assistant_input)

        return (tools, threshold, trim_assistant)
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return None
    except ValueError:
        print("Invalid value entered.")
        return None


def show_action_menu(
    session_id: str,
    agent: str,
    project_name: str,
    git_branch: Optional[str] = None,
    is_sidechain: bool = False,
    stderr_mode: bool = False,
) -> Optional[str]:
    """
    Show action menu for selected session.

    Args:
        session_id: The session identifier (first 8 chars displayed)
        agent: Agent type ('claude' or 'codex')
        project_name: Project or working directory name
        git_branch: Optional git branch name
        is_sidechain: If True, this is a sub-agent session (no resume)
        stderr_mode: If True, prompt via stderr for shell mode

    Returns:
        Action choice: 'resume', 'suppress_resume', 'smart_trim_resume',
        'path', 'copy', 'clone', 'export', or None if cancelled
    """
    print(f"\n=== Session: {session_id[:8]}... ===")
    print(f"Project: {project_name}")
    if git_branch:
        print(f"Branch: {git_branch}")

    if is_sidechain:
        print(
            "\n[Note: This is a sub-agent session and cannot be "
            "resumed directly]"
        )
        print(f"\nWhat would you like to do?")
        print("1. Show session file path")
        print("2. Copy session file to file (*.jsonl) or directory")
        print("3. Export to text file (.txt)")
        print()

        try:
            choice = input("Enter choice [1-3] (or Enter to cancel): ").strip()
            if not choice:
                print("Cancelled.")
                return None
            elif choice == "1":
                return "path"
            elif choice == "2":
                return "copy"
            elif choice == "3":
                return "export"
            else:
                print("Invalid choice.")
                return None
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return None
    else:
        print(f"\nWhat would you like to do?")
        print("1. Resume session (default)")
        print("2. Show session file path")
        print("3. Copy session file to file (*.jsonl) or directory")
        print("4. Clone session and resume clone")
        print("5. Export to text file (.txt)")
        print("6. Continue with context in fresh session")
        print()

        try:
            choice = input("Enter choice [1-6] (or Enter for 1): ").strip()
            if not choice or choice == "1":
                # Show resume submenu
                return show_resume_submenu(stderr_mode=stderr_mode)
            elif choice == "2":
                return "path"
            elif choice == "3":
                return "copy"
            elif choice == "4":
                return "clone"
            elif choice == "5":
                return "export"
            elif choice == "6":
                return "continue"
            else:
                print("Invalid choice.")
                return None
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return None
