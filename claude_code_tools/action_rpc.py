"""Action RPC for Node UI non-launch actions.

Reads a JSON request from stdin, executes the requested action using existing
backend functions, and writes a JSON response to stdout.

Request schema (stdin JSON):
{
  "action": "path" | "copy" | "export",
  "agent": "claude" | "codex",
  "session_id": "...",           # required for claude
  "file_path": "...",            # required for codex
  "cwd": "...",                  # project path
  "claude_home": "...",          # optional
  "dest": "..."                  # required for copy/export
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

    if action not in {"path", "copy", "export", "lineage"}:
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

    except Exception as exc:  # noqa: BLE001
        _error(str(exc))


if __name__ == "__main__":
    main()
