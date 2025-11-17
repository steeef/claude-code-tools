#!/usr/bin/env python3
"""
Trim CLI agent JSONL session files to reduce size.

This script processes JSONL session logs from Claude Code or Codex and
trims content to reduce file size while preserving conversation flow:
- Replaces large tool results with placeholder text
- Optionally trims assistant messages
"""

import argparse
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Set, Tuple

from . import trim_session_claude as claude_processor
from . import trim_session_codex as codex_processor
from .session_utils import get_claude_home, resolve_session_path


def is_trimmed_session(session_file: Path) -> bool:
    """
    Check if a session file is a trimmed session.

    Args:
        session_file: Path to session JSONL file.

    Returns:
        True if session has trim_metadata, False otherwise.
    """
    import json

    if not session_file.exists():
        return False

    try:
        with open(session_file, "r") as f:
            first_line = f.readline().strip()
            if not first_line:
                return False

            data = json.loads(first_line)
            return "trim_metadata" in data
    except (json.JSONDecodeError, IOError):
        return False


def extract_session_info(input_file: Path, agent: str) -> dict:
    """
    Extract session info needed for resuming.

    Args:
        input_file: Path to session JSONL file.
        agent: Agent type ('claude' or 'codex').

    Returns:
        Dict with cwd/project info.
    """
    import json

    with open(input_file, "r") as f:
        for line in f:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            if agent == "claude":
                # Extract cwd from any event
                if "cwd" in data:
                    return {"cwd": data["cwd"]}
            elif agent == "codex":
                # Extract cwd from session_meta
                if data.get("type") == "session_meta":
                    payload = data.get("payload", {})
                    if "cwd" in payload:
                        return {"cwd": payload["cwd"]}

    return {"cwd": None}


def detect_agent(input_file: Path) -> str:
    """
    Auto-detect agent type from session file structure.

    Args:
        input_file: Path to session JSONL file.

    Returns:
        "claude" or "codex"
    """
    import json

    # Read first 20 lines to detect structure
    with open(input_file, "r") as f:
        for i, line in enumerate(f):
            if i >= 20:
                break
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Codex indicators
            if data.get("type") == "session_meta":
                return "codex"
            if data.get("type") == "response_item" and "payload" in data:
                return "codex"

            # Claude indicators
            if "sessionId" in data:
                return "claude"
            if data.get("type") in ["user", "assistant"] and "message" in data:
                return "claude"

    # Default to claude if uncertain
    return "claude"


def create_placeholder(tool_name: str, original_length: int) -> str:
    """
    Create a placeholder string for suppressed content.

    Args:
        tool_name: Name of the tool.
        original_length: Original content length in characters.

    Returns:
        Placeholder string.
    """
    return (
        f"[Results from {tool_name} tool suppressed - "
        f"original content was {original_length:,} characters]"
    )


def trim_and_create_session(
    agent: Optional[str],
    input_file: Path,
    target_tools: Optional[Set[str]],
    threshold: int,
    output_dir: Optional[Path] = None,
    trim_assistant_messages: Optional[int] = None,
) -> dict:
    """
    Trim tool results and assistant messages, creating a new session file.

    Args:
        agent: Agent type ('claude' or 'codex'). If None, auto-detects from file.
        input_file: Path to input JSONL file.
        target_tools: Set of tool names to suppress (None means all).
        threshold: Minimum length threshold for trimming.
        output_dir: Output directory (None = auto-detect based on agent).
        trim_assistant_messages: Optional trimming of assistant messages:
            - Positive N: trim first N assistant messages exceeding threshold
            - Negative N: trim all except last abs(N) assistant messages exceeding threshold
            - None: don't trim assistant messages

    Returns:
        Dict with:
            - session_id: New session UUID
            - output_file: Path to new session file
            - num_tools_trimmed: Number of tool results trimmed
            - num_assistant_trimmed: Number of assistant messages trimmed
            - chars_saved: Characters saved
            - tokens_saved: Estimated tokens saved
            - detected_agent: Detected agent type
    """
    import json
    from datetime import datetime, timezone

    # Auto-detect agent if not specified
    if agent is None:
        agent = detect_agent(input_file)

    # Generate session UUID
    session_uuid = str(uuid.uuid4())

    # Determine output directory and filename based on agent
    if agent == "codex":
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%dT%H-%M-%S")
        date_path = now.strftime("%Y/%m/%d")
        output_filename = (
            f"rollout-{timestamp}-{session_uuid}{input_file.suffix}"
        )

        if output_dir:
            final_output_dir = output_dir / date_path
        else:
            # Find sessions root by going up from input file
            sessions_root = input_file.parent.parent.parent.parent
            final_output_dir = sessions_root / date_path

        final_output_dir.mkdir(parents=True, exist_ok=True)
    else:  # claude
        output_filename = f"{session_uuid}{input_file.suffix}"
        final_output_dir = output_dir if output_dir else input_file.parent

    output_path = final_output_dir / output_filename

    # Process the session
    num_tools_trimmed, num_assistant_trimmed, chars_saved = process_session(
        agent,
        input_file,
        output_path,
        target_tools,
        threshold,
        verbose=False,
        new_session_id=session_uuid,
        trim_assistant_messages=trim_assistant_messages,
    )

    # Estimate tokens saved
    tokens_saved = int(chars_saved / 4)

    # Add trim metadata to first line of output file
    metadata_fields = {
        "trim_metadata": {
            "parent_file": str(input_file.absolute()),
            "trimmed_at": datetime.now(timezone.utc).isoformat(),
            "trim_params": {
                "threshold": threshold,
                "tools": list(target_tools) if target_tools else None,
                "trim_assistant_messages": trim_assistant_messages,
            },
            "stats": {
                "num_tools_trimmed": num_tools_trimmed,
                "num_assistant_trimmed": num_assistant_trimmed,
                "tokens_saved": tokens_saved,
            },
        }
    }

    # Read the file and modify first line
    with open(output_path, "r") as f:
        lines = f.readlines()

    if lines:
        try:
            # Parse first line and add metadata fields
            first_line_data = json.loads(lines[0])
            first_line_data.update(metadata_fields)
            lines[0] = json.dumps(first_line_data) + "\n"

            # Write back the modified file
            with open(output_path, "w") as f:
                f.writelines(lines)
        except json.JSONDecodeError:
            # If first line is not valid JSON, leave file as-is
            pass

    return {
        "session_id": session_uuid,
        "output_file": str(output_path),
        "num_tools_trimmed": num_tools_trimmed,
        "num_assistant_trimmed": num_assistant_trimmed,
        "chars_saved": chars_saved,
        "tokens_saved": tokens_saved,
        "detected_agent": agent,
    }


def process_session(
    agent: str,
    input_file: Path,
    output_file: Path,
    target_tools: Optional[Set[str]],
    threshold: int,
    verbose: bool = True,
    new_session_id: Optional[str] = None,
    trim_assistant_messages: Optional[int] = None,
) -> Tuple[int, int, int]:
    """
    Process session file and trim tool results and assistant messages.

    Args:
        agent: Agent type ('claude' or 'codex').
        input_file: Path to input JSONL file.
        output_file: Path to output JSONL file.
        target_tools: Set of tool names to suppress (None means all).
        threshold: Minimum length threshold for trimming.
        verbose: Whether to print progress messages.
        new_session_id: Optional new session ID to replace in session metadata.
        trim_assistant_messages: Optional trimming of assistant messages (see trim_and_create_session).

    Returns:
        Tuple of (num_tools_trimmed, num_assistant_trimmed, chars_saved).
    """
    if verbose:
        print("Building tool name mapping...", file=sys.stderr)

    if agent == "claude":
        tool_map = claude_processor.build_tool_name_mapping(input_file)
        if verbose:
            print(
                f"Found {len(tool_map)} tool invocations", file=sys.stderr
            )
            print("Processing session...", file=sys.stderr)

        return claude_processor.process_claude_session(
            input_file,
            output_file,
            tool_map,
            target_tools,
            threshold,
            create_placeholder,
            new_session_id=new_session_id,
            trim_assistant_messages=trim_assistant_messages,
        )
    elif agent == "codex":
        tool_map = codex_processor.build_tool_name_mapping(input_file)
        if verbose:
            print(
                f"Found {len(tool_map)} tool invocations", file=sys.stderr
            )
            print("Processing session...", file=sys.stderr)

        return codex_processor.process_codex_session(
            input_file,
            output_file,
            tool_map,
            target_tools,
            threshold,
            create_placeholder,
            new_session_id=new_session_id,
            trim_assistant_messages=trim_assistant_messages,
        )
    else:
        raise ValueError(f"Unknown agent type: {agent}")


def main() -> None:
    """Parse arguments and process the JSONL file."""
    parser = argparse.ArgumentParser(
        description="Trim JSONL session files to reduce size.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Trim all tool results over 500 chars (auto-detects agent)
  %(prog)s session.jsonl

  # Trim only specific tools
  %(prog)s session.jsonl --tools bash,read,edit

  # Use custom length threshold
  %(prog)s session.jsonl --len 1000

  # Trim first 100 assistant messages over threshold
  %(prog)s session.jsonl --trim-assistant-messages 100

  # Trim all assistant messages except last 10 over threshold
  %(prog)s session.jsonl --trim-assistant-messages -10

  # Manually specify agent (usually not needed)
  %(prog)s session.jsonl --agent codex

  # Custom output directory
  %(prog)s session.jsonl --output-dir /tmp
        """,
    )

    parser.add_argument(
        "input_file",
        nargs='?',
        help="Session file path or session ID (optional - uses $CLAUDE_SESSION_ID if not provided)"
    )
    parser.add_argument(
        "--agent",
        "-a",
        choices=["claude", "codex"],
        help="Agent type: claude or codex (auto-detected if not specified)",
    )
    parser.add_argument(
        "--tools",
        "-t",
        help="Comma-separated list of tool names to trim "
        "(e.g., 'bash,read,edit'). If not specified, all tools are "
        "candidates for trimming.",
    )
    parser.add_argument(
        "--len",
        "-l",
        type=int,
        default=500,
        help="Minimum length threshold in characters for trimming "
        "(default: 500)",
    )
    parser.add_argument(
        "--trim-assistant-messages",
        type=int,
        help="Trim assistant messages: positive N trims first N messages "
        "exceeding threshold, negative N trims all except last abs(N) "
        "messages exceeding threshold",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        help="Output directory (default: same as input file)",
    )
    parser.add_argument(
        "--claude-home",
        type=str,
        help="Path to Claude home directory (default: ~/.claude)"
    )

    args = parser.parse_args()

    # Handle input file resolution
    if args.input_file is None:
        # Try to get session ID from environment variable
        session_id = os.environ.get('CLAUDE_SESSION_ID')
        if not session_id:
            print(f"Error: No session file provided and CLAUDE_SESSION_ID not set", file=sys.stderr)
            print(f"Usage: trim-session <session-file-or-id> or run from within Claude Code with !trim-session", file=sys.stderr)
            sys.exit(1)

        # Reconstruct Claude Code session file path
        cwd = os.getcwd()
        base_dir = get_claude_home(args.claude_home)
        encoded_path = cwd.replace("/", "-")
        claude_project_dir = base_dir / "projects" / encoded_path
        input_path = claude_project_dir / f"{session_id}.jsonl"

        if not input_path.exists():
            print(f"Error: Session file not found: {input_path}", file=sys.stderr)
            print(f"(Reconstructed from CLAUDE_SESSION_ID={session_id})", file=sys.stderr)
            sys.exit(1)

        print(f"📋 Using current Claude Code session: {session_id}")
    else:
        # Resolve session ID or path to full path
        try:
            input_path = resolve_session_path(args.input_file, claude_home=args.claude_home)
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    # Auto-detect agent and warn if user specified wrong one
    detected_agent = detect_agent(input_path)
    if args.agent and args.agent != detected_agent:
        print(
            f"⚠️  Detected {detected_agent} session, ignoring --agent {args.agent} argument",
            file=sys.stderr,
        )
    agent_to_use = detected_agent

    # Parse tool names
    target_tools = None
    if args.tools:
        target_tools = {
            tool.strip().lower() for tool in args.tools.split(",")
        }
        print(
            f"Trimming tools: {', '.join(sorted(target_tools))}",
            file=sys.stderr,
        )
    else:
        print(
            "Trimming all tools (no --tools specified)",
            file=sys.stderr,
        )

    print(f"Agent: {agent_to_use}", file=sys.stderr)
    print(f"Length threshold: {args.len} characters", file=sys.stderr)

    if args.trim_assistant_messages:
        if args.trim_assistant_messages > 0:
            print(
                f"Trimming first {args.trim_assistant_messages} assistant messages "
                f"exceeding threshold",
                file=sys.stderr,
            )
        else:
            print(
                f"Trimming all assistant messages except last "
                f"{abs(args.trim_assistant_messages)} exceeding threshold",
                file=sys.stderr,
            )

    # Process the file using helper function
    print(f"\nInput: {input_path}", file=sys.stderr)

    output_dir = Path(args.output_dir) if args.output_dir else None
    result = trim_and_create_session(
        agent_to_use,
        input_path,
        target_tools,
        args.len,
        output_dir,
        args.trim_assistant_messages,
    )

    # Print statistics
    print("\n" + "=" * 70)
    print("TRIM SUMMARY")
    print("=" * 70)
    print(f"Agent: {result['detected_agent']}")
    print(f"Tool results trimmed: {result['num_tools_trimmed']}")
    print(f"Assistant messages trimmed: {result['num_assistant_trimmed']}")
    print(f"Characters saved: {result['chars_saved']:,}")
    print(f"Estimated tokens saved: {result['tokens_saved']:,}")
    print("")
    print(f"Output file: {result['output_file']}")
    print("")
    print("Session UUID:")
    print(result["session_id"])
    print("=" * 70)

    # Extract session info for resuming
    session_info = extract_session_info(input_path, result["detected_agent"])
    cwd = session_info.get("cwd")

    # Construct resume command based on agent type
    agent_name = result["detected_agent"]
    session_id = result["session_id"]
    output_file = result["output_file"]

    if agent_name == "claude":
        # Claude uses --resume with session ID
        if cwd:
            resume_cmd = f"cd {cwd} && claude --resume {session_id}"
        else:
            resume_cmd = f"claude --resume {session_id}"
        resume_args = ["claude", "--resume", session_id]
    else:  # codex
        # Codex uses 'resume' subcommand with session ID
        if cwd:
            resume_cmd = f"cd {cwd} && codex resume {session_id}"
        else:
            resume_cmd = f"codex resume {session_id}"
        resume_args = ["codex", "resume", session_id]

    # Interactive prompt
    print("\n")
    try:
        response = input("Resume this session now? [Y/n]: ").strip().lower()
        if response in ["n", "no"]:
            print(f"\nTo resume later, run:")
            print(f"  {resume_cmd}")
        else:
            # Default to yes (empty input or "y"/"yes")
            print(f"\n🚀 Resuming session...\n")
            import subprocess

            # Change to cwd if specified, then run the agent
            if cwd:
                os.chdir(cwd)

            subprocess.run(resume_args)
    except (KeyboardInterrupt, EOFError):
        print(f"\n\nTo resume later, run:")
        print(f"  {resume_cmd}")


if __name__ == "__main__":
    main()
