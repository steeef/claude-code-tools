"""Bridge to Node-based session UI.

Provides a thin IPC wrapper that launches the Node menu renderer, passes
sessions/keywords, and dispatches the selected action back into Python via the
provided action_handler.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List

SessionDict = Dict[str, Any]


def _node_script_path() -> Path:
    """Return path to the bundled Node UI script."""
    here = Path(__file__).resolve()
    return here.parent.parent / "node_ui" / "menu.js"


def _write_payload(
    sessions: Iterable[SessionDict],
    keywords: List[str],
    focus_id: str | None = None,
    start_action: bool = False,
    start_screen: str | None = None,
    rpc_path: str | None = None,
    scope_line: str | None = None,
    tip_line: str | None = None,
) -> Path:
    """Write payload to a temp file and return its path."""
    payload = {
        "sessions": list(sessions),
        "keywords": keywords,
        "focus_id": focus_id,
        "start_action": start_action,
        "start_screen": start_screen,
        "rpc_path": rpc_path,
        "scope_line": scope_line,
        "tip_line": tip_line,
    }
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix="-node-ui.json")
    Path(tmp.name).write_text(json.dumps(payload), encoding="utf-8")
    return Path(tmp.name)


def _run_node(data_path: Path, out_path: Path, stderr_mode: bool = False) -> int:
    """Invoke the Node UI process.

    Returns the process return code.
    """
    script = _node_script_path()
    cmd = ["node", str(script), "--data", str(data_path), "--out", str(out_path)]
    env = os.environ.copy()
    if stderr_mode:
        env["NODE_UI_STDERR"] = "1"

    proc = subprocess.run(cmd, env=env)
    return proc.returncode


def _read_result(out_path: Path) -> Dict[str, Any]:
    """Read the result file if it exists, else return empty dict."""
    import time

    # Small retry loop in case file isn't fully synced yet
    for _ in range(3):
        if not out_path.exists():
            time.sleep(0.05)
            continue
        try:
            content = out_path.read_text(encoding="utf-8").strip()
            if content:
                return json.loads(content)
        except (json.JSONDecodeError, IOError):
            pass
        time.sleep(0.05)
    return {}


def run_node_menu_ui(
    sessions: List[SessionDict],
    keywords: List[str],
    action_handler: Callable[[SessionDict, str, Dict[str, Any]], None],
    stderr_mode: bool = False,
    focus_session_id: str | None = None,
    start_action: bool = False,
    start_screen: str | None = None,
    rpc_path: str | None = None,
    scope_line: str | None = None,
    tip_line: str | None = None,
) -> None:
    """Launch Node UI and dispatch selected action.

    Args:
        sessions: List of session dicts (same shape as find_session results)
        keywords: List of search keywords
        action_handler: Callback invoked with (session_dict, action)
        stderr_mode: If True, Node may log to stderr instead of stdout
        start_screen: Optional screen to start on ('action', 'resume', etc.)
    """
    data_path = _write_payload(
        sessions,
        keywords,
        focus_id=focus_session_id,
        start_action=start_action,
        start_screen=start_screen,
        rpc_path=rpc_path,
        scope_line=scope_line,
        tip_line=tip_line,
    )
    out_fd, out_path = tempfile.mkstemp(suffix="-node-ui-out.json")
    os.close(out_fd)
    out_file = Path(out_path)

    try:
        code = _run_node(data_path, out_file, stderr_mode=stderr_mode)
        if code != 0:
            print("Node UI exited with code", code, file=sys.stderr)
            return

        result = _read_result(out_file)
        session_id = result.get("session_id")
        action = result.get("action")
        kwargs = result.get("kwargs", {})
        if not session_id or not action:
            # Empty result means user cancelled (Escape) - silently return
            if result:
                # Non-empty but malformed result is an actual error
                print(f"Error: Missing session_id or action in result: {result}")
            return

        # Locate matching session
        session = next((s for s in sessions if s.get("session_id") == session_id), None)
        if not session:
            print(f"Error: Session {session_id} not found in {len(sessions)} sessions")
            return

        action_handler(session, action, kwargs)
    finally:
        try:
            data_path.unlink(missing_ok=True)  # type: ignore[arg-type]
        except Exception:
            pass
        try:
            out_file.unlink(missing_ok=True)  # type: ignore[arg-type]
        except Exception:
            pass
