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

    if not prompt.startswith(">resume"):
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

    if copied:
        message = (
            f"Session ID copied to clipboard!\n\n"
            f"To continue your work from this session:\n"
            f"  1. Quit Claude (Ctrl+D twice)\n"
            f"  2. Run: aichat resume <paste>\n\n"
            f"Session ID: {session_id}"
        )
    else:
        message = (
            f"Could not copy to clipboard. Here's your session ID:\n\n"
            f"  {session_id}\n\n"
            f"To continue your work from this session:\n"
            f"  1. Copy the session ID above\n"
            f"  2. Quit Claude (Ctrl+D twice)\n"
            f"  3. Run: aichat resume <session-id>"
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
