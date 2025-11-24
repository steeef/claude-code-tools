"""Test that Codex clone_session works with session_menu_cli calling pattern."""

import tempfile
from pathlib import Path
import uuid
import pytest
from unittest.mock import patch

from claude_code_tools.find_codex_session import clone_session
from claude_code_tools.session_menu_cli import execute_action


def test_clone_session_with_incomplete_args_fails():
    """Test that calling clone_session without session_id and cwd fails."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session_id = str(uuid.uuid4())
        filename = f"rollout-2025-11-23T17-50-57-{session_id}.jsonl"
        session_file = Path(tmpdir) / filename
        session_file.write_text('{"type":"session_meta","payload":{"cwd":"/test"}}\n')

        # This is how session_menu_cli.py CURRENTLY calls it (WRONG)
        with pytest.raises(TypeError, match="missing.*required positional"):
            clone_session(
                str(session_file),
                shell_mode=False,
                codex_home=tmpdir
            )


def test_clone_session_with_menu_cli_pattern():
    """Test clone_session called the way session_menu_cli.py calls it."""
    # Create a temporary session file
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a fake session file with proper Codex naming format
        session_id = str(uuid.uuid4())
        filename = f"rollout-2025-11-23T17-50-57-{session_id}.jsonl"
        session_file = Path(tmpdir) / filename

        # Write minimal valid Codex session content
        session_file.write_text('{"type":"session_meta","payload":{"cwd":"/test"}}\n')

        # Call it the way session_menu_cli.py does at line 293-295
        # This matches the actual usage pattern: positional args for file_path,
        # session_id, cwd, then keyword args
        try:
            clone_session(
                str(session_file),  # file_path (positional)
                session_id,          # session_id (positional)
                "/test",             # cwd (positional)
                shell_mode=True,     # keyword arg
                codex_home=tmpdir    # keyword arg
            )
            # Success - no TypeError
        except TypeError as e:
            # If we get TypeError about missing arguments or unexpected keyword,
            # that's a test failure
            if "missing" in str(e) or "unexpected keyword" in str(e):
                raise AssertionError(
                    f"clone_session signature should accept these arguments: {e}"
                )
            # Other errors (e.g., codex command not found) are okay
            pass


def test_session_menu_cli_clone_codex_session():
    """Test that session_menu_cli calls clone_session correctly for Codex."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a fake Codex session file
        session_id = str(uuid.uuid4())
        filename = f"rollout-2025-11-23T17-50-57-{session_id}.jsonl"
        session_file = Path(tmpdir) / filename
        session_file.write_text('{"type":"session_meta","payload":{"cwd":"/test"}}\n')

        # Mock os.execvp to avoid actually launching codex
        # Mock input() to avoid interactive prompts
        with patch('os.execvp'), patch('builtins.input', return_value='n'):
            # This should NOT raise TypeError
            # execute_action calls clone_session the way it's used in production
            try:
                execute_action(
                    action="clone",
                    agent="codex",
                    session_file=session_file,
                    project_path="/test",
                    claude_home=None,
                    codex_home=tmpdir
                )
                # Success - no TypeError
            except TypeError as e:
                if "missing" in str(e) or "unexpected keyword" in str(e):
                    pytest.fail(
                        f"execute_action should pass correct arguments to clone_session: {e}"
                    )
                # Other errors are okay
                pass

