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
    select_target: str | None = None,
    results_title: str | None = None,
    start_zoomed: bool = False,
    lineage_back_target: str | None = None,
    direct_action: str | None = None,
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
        "select_target": select_target,
        "results_title": results_title,
        "start_zoomed": start_zoomed,
        "lineage_back_target": lineage_back_target,
        "direct_action": direct_action,
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


def _run_node_menu_once(
    sessions: List[SessionDict],
    keywords: List[str],
    action_handler: Callable[[SessionDict, str, Dict[str, Any]], Any],
    stderr_mode: bool,
    focus_session_id: str | None,
    start_action: bool,
    start_screen: str | None,
    rpc_path: str | None,
    scope_line: str | None,
    tip_line: str | None,
    select_target: str | None,
    results_title: str | None,
    start_zoomed: bool,
    lineage_back_target: str | None,
    direct_action: str | None,
) -> str | None:
    """Run Node UI once and return result signal.

    Returns:
        'back' - action_handler wants to go back to resume menu
        'back_to_options' - user wants to go back to options
        None - normal exit (action completed or user cancelled)
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
        select_target=select_target,
        results_title=results_title,
        start_zoomed=start_zoomed,
        lineage_back_target=lineage_back_target,
        direct_action=direct_action,
    )
    out_fd, out_path = tempfile.mkstemp(suffix="-node-ui-out.json")
    os.close(out_fd)
    out_file = Path(out_path)

    try:
        code = _run_node(data_path, out_file, stderr_mode=stderr_mode)
        if code != 0:
            print("Node UI exited with code", code, file=sys.stderr)
            return None

        result = _read_result(out_file)
        session_id = result.get("session_id")
        action = result.get("action")
        kwargs = result.get("kwargs", {})

        if action == "back_to_options":
            return "back_to_options"

        if not session_id or not action:
            if result:
                print(f"Error: Missing session_id or action in result: {result}")
            return None

        session = next((s for s in sessions if s.get("session_id") == session_id), None)
        if not session:
            print(f"Error: Session {session_id} not found in {len(sessions)} sessions")
            return None

        handler_result = action_handler(session, action, kwargs)
        return 'back' if handler_result == 'back' else None
    finally:
        try:
            data_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            out_file.unlink(missing_ok=True)
        except Exception:
            pass


def run_node_menu_ui(
    sessions: List[SessionDict],
    keywords: List[str],
    action_handler: Callable[[SessionDict, str, Dict[str, Any]], Any],
    stderr_mode: bool = False,
    focus_session_id: str | None = None,
    start_action: bool = False,
    start_screen: str | None = None,
    rpc_path: str | None = None,
    scope_line: str | None = None,
    tip_line: str | None = None,
    select_target: str | None = None,
    results_title: str | None = None,
    start_zoomed: bool = False,
    lineage_back_target: str | None = None,
    direct_action: str | None = None,
    exit_on_back: bool = False,
) -> str | None:
    """Launch Node UI and dispatch selected action.

    Handles 'back to resume' internally - if action_handler returns 'back',
    automatically re-shows the resume menu (unless exit_on_back=True).

    Args:
        exit_on_back: If True, return 'back' to caller instead of looping to
            resume menu. Use this when invoking from Rust search where we want
            to pop back to search results on cancel.

    Returns:
        "back_to_options" if user wants to go back to options menu.
        "back" if exit_on_back=True and action was cancelled.
        None otherwise.
    """
    current_screen = start_screen
    current_direct_action = direct_action
    current_start_action = start_action

    while True:
        result = _run_node_menu_once(
            sessions, keywords, action_handler, stderr_mode, focus_session_id,
            current_start_action, current_screen, rpc_path, scope_line, tip_line,
            select_target, results_title, start_zoomed, lineage_back_target,
            current_direct_action,
        )

        if result == 'back':
            if exit_on_back:
                # Return to caller (for Rust search pop-back)
                return 'back'
            # Go back to resume menu
            current_screen = 'resume'
            current_direct_action = None
            current_start_action = False  # Don't auto-start action on loop back
            continue

        # 'back_to_options' or None - return to caller
        return result


def run_find_options_ui(
    initial_options: Dict[str, Any],
    variant: str = "find",
) -> Dict[str, Any] | None:
    """
    Launch Node UI to interactively configure find options.

    Args:
        initial_options: Dict with initial option values (keywords, global, etc.)
        variant: One of 'find', 'find-claude', 'find-codex'

    Returns:
        Dict with user-selected options, or None if cancelled
    """
    payload = {
        "sessions": [],
        "keywords": [],
        "start_screen": "find_options",
        "find_options": initial_options,
        "find_variant": variant,
    }

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix="-find-opts.json")
    Path(tmp.name).write_text(json.dumps(payload), encoding="utf-8")
    data_path = Path(tmp.name)

    out_fd, out_path = tempfile.mkstemp(suffix="-find-opts-out.json")
    os.close(out_fd)
    out_file = Path(out_path)

    try:
        code = _run_node(data_path, out_file)
        if code != 0:
            return None

        result = _read_result(out_file)
        return result.get("find_options")
    finally:
        try:
            data_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            out_file.unlink(missing_ok=True)
        except Exception:
            pass


def run_trim_confirm_ui(
    new_session_id: str | None = None,
    lines_trimmed: int = 0,
    tokens_saved: int = 0,
    output_file: str = "",
    nothing_to_trim: bool = False,
    original_session_id: str | None = None,
) -> str | None:
    """
    Launch Node UI to confirm trim action.

    Shows a confirmation dialog after a trim operation. Can handle two cases:
    1. Trim created a new file - shows Resume/Delete options
    2. Nothing to trim - shows Resume original/Back options

    Args:
        new_session_id: The newly created session ID (None if nothing_to_trim)
        lines_trimmed: Number of lines that were trimmed
        tokens_saved: Estimated tokens saved
        output_file: Path to the new session file
        nothing_to_trim: If True, show "nothing to trim" UI variant
        original_session_id: Original session ID (used when nothing_to_trim)

    Returns:
        'resume' - User wants to resume the session
        'delete' - User wants to delete the new file and exit
        'back' - User wants to go back to menu (nothing_to_trim case)
        'cancel' - User pressed Escape (keep file, don't resume)
        None - Error or unexpected result
    """
    payload = {
        "sessions": [],
        "keywords": [],
        "start_screen": "trim_confirm",
        "trim_info": {
            "new_session_id": new_session_id,
            "original_session_id": original_session_id,
            "lines_trimmed": lines_trimmed,
            "tokens_saved": tokens_saved,
            "output_file": output_file,
            "nothing_to_trim": nothing_to_trim,
        },
    }

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix="-trim-confirm.json")
    Path(tmp.name).write_text(json.dumps(payload), encoding="utf-8")
    data_path = Path(tmp.name)

    out_fd, out_path = tempfile.mkstemp(suffix="-trim-confirm-out.json")
    os.close(out_fd)
    out_file = Path(out_path)

    try:
        code = _run_node(data_path, out_file)
        if code != 0:
            return None

        result = _read_result(out_file)
        return result.get("trim_action")
    finally:
        try:
            data_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            out_file.unlink(missing_ok=True)
        except Exception:
            pass
