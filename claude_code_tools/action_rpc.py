"""Action RPC for Node UI non-launch actions.

Reads a JSON request from stdin, executes the requested action using existing
backend functions, and writes a JSON response to stdout.

Request schema (stdin JSON):
{
  "action": "path" | "copy" | "export" | "query",
  "agent": "claude" | "codex",
  "session_id": "...",           # required for claude
  "file_path": "...",            # required for codex
  "cwd": "...",                  # project path
  "claude_home": "...",          # optional
  "dest": "...",                 # required for copy/export
  "query": "..."                 # required for query action
}

Response schema (stdout JSON):
{
  "status": "ok" | "error",
  "message": "...",             # human-readable
  "path": "..."                 # for path/export destination
}
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict

import contextlib
import io

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent))


def _error(msg: str) -> None:
    sys.stdout.write(json.dumps({"status": "error", "message": msg}) + "\n")
    sys.exit(0)


def _ok(message: str, path: str | None = None) -> None:
    payload: Dict[str, Any] = {"status": "ok", "message": message}
    if path:
        payload["path"] = path
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.exit(0)


def _quiet_call(func, *args, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        return func(*args, **kwargs)


def main() -> None:
    try:
        request = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        _error("Invalid JSON request")

    action = request.get("action")
    agent = request.get("agent")
    session_id = request.get("session_id")
    file_path = request.get("file_path")
    cwd = request.get("cwd")
    claude_home = request.get("claude_home")
    dest = request.get("dest")
    query = request.get("query")

    if action not in {"path", "copy", "export", "lineage", "query"}:
        _error("Unsupported action")
    if agent not in {"claude", "codex"}:
        _error("Unsupported agent")

    try:
        if action == "path":
            if agent == "claude":
                from claude_code_tools.find_claude_session import (
                    get_session_file_path,
                )

                if not session_id or not cwd:
                    _error("Missing session_id or cwd")
                path = get_session_file_path(session_id, cwd, claude_home=claude_home)
                _ok(path, path)
            else:
                if not file_path:
                    _error("Missing file_path")
                _ok(file_path, file_path)

        elif action == "copy":
            if not dest:
                _error("Missing dest")
            if agent == "claude":
                from claude_code_tools.find_claude_session import (
                    get_session_file_path,
                    copy_session_file,
                )

                if not session_id or not cwd:
                    _error("Missing session_id or cwd")
                src = get_session_file_path(session_id, cwd, claude_home=claude_home)
                _quiet_call(copy_session_file, src, dest_override=dest, silent=True)
                _ok(f"Copied to {dest}", dest)
            else:
                from claude_code_tools.find_codex_session import copy_session_file

                if not file_path:
                    _error("Missing file_path")
                _quiet_call(copy_session_file, file_path, dest_override=dest, silent=True)
                _ok(f"Copied to {dest}", dest)

        elif action == "export":
            if not dest:
                today = datetime.now().strftime("%Y%m%d")
                session_stem = None
                if file_path:
                    session_stem = Path(file_path).stem
                elif session_id:
                    session_stem = session_id
                if not session_stem:
                    _error("Missing dest and session info")
                prefix = "codex" if agent == "codex" else "claude"
                # Use session's project directory if available, fallback to cwd
                base_dir = Path(cwd) if cwd else Path.cwd()
                dest = str(
                    base_dir
                    / "exported-sessions"
                    / f"{today}-{prefix}-session-{session_stem}.txt"
                )
            if agent == "claude":
                from claude_code_tools.export_claude_session import (
                    export_session_to_markdown,
                )

                if not file_path:
                    if not session_id or not cwd:
                        _error("Missing session_id or cwd")
                    from claude_code_tools.find_claude_session import get_session_file_path

                    file_path = get_session_file_path(
                        session_id, cwd, claude_home=claude_home
                    )
                dest_path = Path(dest)
                if dest_path.suffix != ".txt":
                    dest_path = dest_path.with_suffix(".txt")
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "w") as fh:
                    _quiet_call(export_session_to_markdown, Path(file_path), fh, verbose=False)
                _ok(f"Exported to {dest}", str(dest_path))
            else:
                from claude_code_tools.find_codex_session import handle_export_session

                if not file_path:
                    _error("Missing file_path")
                _quiet_call(handle_export_session, file_path, dest_override=dest)
                _ok(f"Exported to {dest}", dest)

        elif action == "lineage":
            # Get continuation lineage for a session
            from claude_code_tools.session_lineage import get_continuation_lineage

            # Prefer file_path if provided, otherwise compute for claude
            if file_path:
                session_path = Path(file_path)
            elif agent == "claude":
                from claude_code_tools.find_claude_session import get_session_file_path

                if not session_id or not cwd:
                    _error("Missing session_id or cwd")
                session_path = Path(get_session_file_path(session_id, cwd, claude_home=claude_home))
            else:
                _error("Missing file_path")

            try:
                lineage = get_continuation_lineage(session_path, export_missing=False)
                lineage_data = []
                for node in lineage:
                    lineage_data.append({
                        "session_file": str(node.session_file.name),
                        "derivation_type": node.derivation_type,
                        "exported_file": str(node.exported_file) if node.exported_file else None,
                    })
                # Return lineage as JSON in message field
                payload = {"status": "ok", "message": "Lineage retrieved", "lineage": lineage_data}
                sys.stdout.write(json.dumps(payload) + "\n")
                sys.exit(0)
            except Exception as e:
                _ok("No lineage found", None)  # Not an error, just no history

        elif action == "query":
            # Query session using agent in non-interactive mode
            if not query:
                _error("Missing query")

            # Get session file path
            if file_path:
                session_path = Path(file_path)
            elif agent == "claude":
                from claude_code_tools.find_claude_session import get_session_file_path

                if not session_id or not cwd:
                    _error("Missing session_id or cwd")
                session_path = Path(
                    get_session_file_path(session_id, cwd, claude_home=claude_home)
                )
            else:
                _error("Missing file_path")

            # Export session to default export location
            from claude_code_tools.session_utils import default_export_path

            export_path = default_export_path(session_path, agent)
            export_path.parent.mkdir(parents=True, exist_ok=True)

            if agent == "claude":
                from claude_code_tools.export_claude_session import (
                    export_session_to_markdown,
                )

                with open(export_path, "w") as fh:
                    _quiet_call(
                        export_session_to_markdown, session_path, fh, verbose=False
                    )
            else:
                from claude_code_tools.find_codex_session import (
                    handle_export_session,
                )

                _quiet_call(
                    handle_export_session, str(session_path), dest_override=str(export_path)
                )

            # Build the prompt - use same style as continue command
            if agent == "claude":
                full_prompt = f"""There is a log of a past conversation with an AI agent in this file: {export_path}

Strategically use PARALLEL SUB-AGENTS to explore {export_path} (which may be very long) to answer the following question:

{query}

DO NOT TRY TO READ {export_path} by YOURSELF! To save your own context, you must use parallel sub-agents, possibly to explore the beginning, middle, and end of that chat.

Provide a clear and concise answer to the question."""
            else:
                full_prompt = f"""There is a log of a past conversation with an AI agent in this file: {export_path}

CAUTION: {export_path} may be very large. Strategically use parallel sub-agents if available, or use another strategy to efficiently read the file so your context window is not overloaded. For example, you could read specific sections (beginning, middle, end) rather than the entire file at once.

Based on the session log, answer the following question:

{query}

Provide a clear and concise answer."""

            # Run the agent in non-interactive mode
            if agent == "claude":
                # Use claude -p for non-interactive mode
                cmd = ["claude", "-p", full_prompt, "--output-format", "json"]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,  # 5 minute timeout (may use sub-agents)
                    stdin=subprocess.DEVNULL,  # Prevent TTY access
                )

                if result.returncode != 0:
                    _error(f"Claude command failed: {result.stderr}")

                # Parse JSON output to get the response
                # Claude outputs JSON with "result" field containing the actual response
                response_text = ""
                for line in result.stdout.strip().splitlines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        if "result" in data:
                            response_text = data["result"]
                            break
                    except json.JSONDecodeError:
                        continue

                if not response_text:
                    # Fallback to raw output if parsing failed
                    response_text = result.stdout.strip()

            else:
                # Use codex exec for non-interactive mode
                cmd = ["codex", "exec", "--json", full_prompt]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,  # 5 minute timeout
                    stdin=subprocess.DEVNULL,  # Prevent TTY access
                )

                if result.returncode != 0:
                    _error(f"Codex command failed: {result.stderr}")

                # Parse JSON stream to get the final response
                # Codex outputs events like:
                # {"type":"item.completed","item":{"type":"agent_message","text":"..."}}
                response_text = ""
                for line in result.stdout.splitlines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                        # Look for item.completed with agent_message type
                        if event.get("type") == "item.completed":
                            item = event.get("item", {})
                            if item.get("type") == "agent_message":
                                text = item.get("text", "")
                                if text:
                                    response_text = text  # Use last agent_message
                        # Also handle message.delta and message.completed formats
                        elif event.get("type") == "message.delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                response_text += delta.get("text", "")
                        elif event.get("type") == "message.completed":
                            content = event.get("content", [])
                            for item in content:
                                if item.get("type") == "text":
                                    response_text = item.get("text", "")
                    except json.JSONDecodeError:
                        continue

                if not response_text:
                    response_text = result.stdout.strip() or "No response received"

            _ok(response_text)

    except Exception as exc:  # noqa: BLE001
        _error(str(exc))


if __name__ == "__main__":
    main()
