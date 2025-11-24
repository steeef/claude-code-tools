"""Test that Codex clone_session accepts codex_home parameter."""

import tempfile
from pathlib import Path
import uuid

from claude_code_tools.find_codex_session import clone_session


def test_clone_session_accepts_codex_home():
    """Test that clone_session accepts codex_home parameter."""
    # Create a temporary session file
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a fake session file with proper Codex naming format
        session_id = str(uuid.uuid4())
        filename = f"rollout-2025-11-23T17-50-57-{session_id}.jsonl"
        session_file = Path(tmpdir) / filename

        # Write minimal valid Codex session content
        session_file.write_text('{"type":"session_meta","payload":{"cwd":"/test"}}\n')

        # This should NOT raise TypeError about codex_home argument
        # We're just testing that the function signature accepts it
        try:
            clone_session(
                file_path=str(session_file),
                session_id=session_id,
                cwd="/test",
                shell_mode=True,  # Use shell mode to avoid interactive prompts
                codex_home=tmpdir  # This should be accepted
            )
            # If we get here without TypeError, the signature is correct
        except TypeError as e:
            if "codex_home" in str(e):
                raise AssertionError(
                    f"clone_session should accept codex_home parameter: {e}"
                )
            # Other TypeErrors might be expected (e.g., codex command not found)
            # We only care about the signature accepting codex_home
            pass
