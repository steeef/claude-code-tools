#!/usr/bin/env python3
"""
Hook to handle '>resume' trigger in Claude Code.

When user types '>resume' in Claude:
1. Copies the current session ID to the clipboard
2. Blocks the prompt (Claude doesn't process it)
3. User can then quit Claude and run: aichat resume <paste>
"""
import json
import subprocess
import sys

# Trigger patterns that activate this hook
TRIGGERS = (">resume", ">continue", ">handoff")


def copy_to_clipboard(text: str) -> bool:
    """
    Copy text to clipboard. Tries multiple commands for cross-platform support.
    Returns True if successful, False otherwise.
    """
    # Commands to try in order (first one that works wins)
    clipboard_commands = [
        ["pbcopy"],  # macOS
        ["xclip", "-selection", "clipboard"],  # Linux X11
        ["xsel", "--clipboard", "--input"],  # Linux X11 alternative
        ["wl-copy"],  # Linux Wayland
        ["clip"],  # Windows
    ]

    for cmd in clipboard_commands:
        try:
            proc = subprocess.run(
                cmd,
                input=text.encode(),
                capture_output=True,
                timeout=5,
            )
            if proc.returncode == 0:
                return True
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            continue

    return False


def main():
    data = json.load(sys.stdin)
    session_id = data.get("session_id", "")
    prompt = data.get("prompt", "").strip()

    if not any(prompt.startswith(t) for t in TRIGGERS):
        # Not our trigger, let it pass through
        sys.exit(0)

    if not session_id:
        # No session ID available
        result = {
            "decision": "block",
            "reason": "No session ID available. Cannot set up resume.",
        }
        print(json.dumps(result))
        sys.exit(0)

    # Try to copy session ID to clipboard
    copied = copy_to_clipboard(session_id)

    # ANSI escape codes for bright blue color and code style
    BLUE = "\033[94m"
    CODE = "\033[37m"  # Regular white for code-like appearance
    RESET = "\033[0m"

    if copied:
        message = (
            f"{BLUE}Session ID copied to clipboard!{RESET}\n\n"
            f"{BLUE}To continue your work in a new session:{RESET}\n"
            f"{BLUE}  1. Quit Claude (Ctrl+D twice){RESET}\n"
            f"{BLUE}  2. Run: {CODE}`aichat resume <paste>`{RESET}\n\n"
            f"{BLUE}You can then choose between a few different ways of{RESET}\n"
            f"{BLUE}continuing your work.{RESET}\n\n"
            f"{BLUE}Session ID: {session_id}{RESET}"
        )
    else:
        message = (
            f"{BLUE}Could not copy to clipboard. Here's your session ID:{RESET}\n\n"
            f"{BLUE}  {session_id}{RESET}\n\n"
            f"{BLUE}To continue your work in a new session:{RESET}\n"
            f"{BLUE}  1. Copy the session ID above{RESET}\n"
            f"{BLUE}  2. Quit Claude (Ctrl+D twice){RESET}\n"
            f"{BLUE}  3. Run: {CODE}`aichat resume <session-id>`{RESET}\n\n"
            f"{BLUE}You can then choose between a few different ways of{RESET}\n"
            f"{BLUE}continuing your work.{RESET}"
        )

    # Block the prompt and show the message
    result = {
        "decision": "block",
        "reason": message,
    }
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
