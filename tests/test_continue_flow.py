"""
Tests for the unified continue flow.

Tests cover:
- is_agent_available() helper
- Agent availability check in continue_with_options()
- Parameter handling (preset_agent, preset_prompt)
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from claude_code_tools.session_utils import (
    is_agent_available,
    continue_with_options,
)


class TestIsAgentAvailable:
    """Tests for is_agent_available() helper."""

    def test_claude_available_via_command(self):
        """Test Claude is available when command exists in PATH."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/claude"
            assert is_agent_available("claude") is True
            mock_which.assert_called_with("claude")

    def test_codex_available_via_command(self):
        """Test Codex is available when command exists in PATH."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/codex"
            assert is_agent_available("codex") is True
            mock_which.assert_called_with("codex")

    def test_claude_available_via_config_dir(self, tmp_path, monkeypatch):
        """Test Claude is available when ~/.claude exists."""
        # Create fake home with .claude directory
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        claude_dir = fake_home / ".claude"
        claude_dir.mkdir()

        with patch("shutil.which", return_value=None):
            with patch.object(Path, "home", return_value=fake_home):
                assert is_agent_available("claude") is True

    def test_codex_available_via_config_dir(self, tmp_path):
        """Test Codex is available when ~/.codex exists."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        codex_dir = fake_home / ".codex"
        codex_dir.mkdir()

        with patch("shutil.which", return_value=None):
            with patch.object(Path, "home", return_value=fake_home):
                assert is_agent_available("codex") is True

    def test_agent_not_available(self, tmp_path):
        """Test agent not available when neither command nor config exists."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        # No .claude or .codex directories

        with patch("shutil.which", return_value=None):
            with patch.object(Path, "home", return_value=fake_home):
                assert is_agent_available("claude") is False
                assert is_agent_available("codex") is False

    def test_case_insensitive(self):
        """Test agent name is case-insensitive."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/claude"
            assert is_agent_available("CLAUDE") is True
            assert is_agent_available("Claude") is True
            assert is_agent_available("claude") is True


class TestContinueWithOptionsParameters:
    """Tests for continue_with_options() parameter handling."""

    @pytest.fixture
    def mock_session_file(self, tmp_path):
        """Create a mock session file."""
        session_file = tmp_path / "test-session.jsonl"
        session_file.write_text(json.dumps({
            "type": "user",
            "sessionId": "test-123",
            "cwd": str(tmp_path),
            "message": {"content": "test"}
        }) + "\n")
        return session_file

    def test_preset_agent_skips_prompt(self, mock_session_file):
        """Test that preset_agent skips the agent choice prompt."""
        with patch(
            "claude_code_tools.session_utils.display_lineage"
        ) as mock_lineage:
            mock_lineage.return_value = ([], mock_session_file)

            with patch(
                "claude_code_tools.session_utils.is_agent_available",
                return_value=True
            ):
                with patch("builtins.input") as mock_input:
                    # Set up mock to fail if called for agent choice
                    # (should not be called since preset_agent is provided)
                    mock_input.return_value = ""  # For custom prompt

                    with patch(
                        "claude_code_tools.claude_continue.claude_continue"
                    ) as mock_continue:
                        continue_with_options(
                            str(mock_session_file),
                            "claude",
                            preset_agent="claude",
                            preset_prompt="",  # Skip custom prompt too
                        )

                        # Should have called claude_continue
                        mock_continue.assert_called_once()

    def test_preset_prompt_skips_input(self, mock_session_file):
        """Test that preset_prompt skips the custom prompt input."""
        with patch(
            "claude_code_tools.session_utils.display_lineage"
        ) as mock_lineage:
            mock_lineage.return_value = ([], mock_session_file)

            with patch(
                "claude_code_tools.session_utils.is_agent_available",
                return_value=False  # Other agent not available, skip choice
            ):
                with patch("builtins.input") as mock_input:
                    with patch(
                        "claude_code_tools.claude_continue.claude_continue"
                    ) as mock_continue:
                        continue_with_options(
                            str(mock_session_file),
                            "claude",
                            preset_prompt="focus on bug fixes",
                        )

                        # input() should NOT have been called
                        mock_input.assert_not_called()

                        # Should have passed custom_prompt to continue
                        call_kwargs = mock_continue.call_args[1]
                        assert call_kwargs["custom_prompt"] == "focus on bug fixes"

    def test_other_agent_unavailable_skips_choice(self, mock_session_file):
        """Test that agent choice is skipped when other agent unavailable."""
        with patch(
            "claude_code_tools.session_utils.display_lineage"
        ) as mock_lineage:
            mock_lineage.return_value = ([], mock_session_file)

            with patch(
                "claude_code_tools.session_utils.is_agent_available",
                return_value=False  # Codex not available
            ):
                with patch("builtins.input") as mock_input:
                    mock_input.return_value = ""  # For custom prompt only

                    with patch(
                        "claude_code_tools.claude_continue.claude_continue"
                    ) as mock_continue:
                        continue_with_options(
                            str(mock_session_file),
                            "claude",
                        )

                        # Should use current agent (claude) without prompting
                        mock_continue.assert_called_once()
                        # input should only be called once (for custom prompt)
                        assert mock_input.call_count == 1


class TestContinueWithOptionsAgentChoice:
    """Tests for agent choice logic in continue_with_options()."""

    @pytest.fixture
    def mock_session_file(self, tmp_path):
        """Create a mock session file."""
        session_file = tmp_path / "test-session.jsonl"
        session_file.write_text(json.dumps({
            "type": "user",
            "sessionId": "test-123",
            "cwd": str(tmp_path),
        }) + "\n")
        return session_file

    def test_cross_agent_choice_codex(self, mock_session_file):
        """Test choosing Codex when continuing Claude session."""
        with patch(
            "claude_code_tools.session_utils.display_lineage"
        ) as mock_lineage:
            mock_lineage.return_value = ([], mock_session_file)

            with patch(
                "claude_code_tools.session_utils.is_agent_available",
                return_value=True
            ):
                with patch("builtins.input") as mock_input:
                    # User chooses option 2 (cross-agent), then empty custom prompt
                    mock_input.side_effect = ["2", ""]

                    with patch(
                        "claude_code_tools.codex_continue.codex_continue"
                    ) as mock_codex:
                        continue_with_options(
                            str(mock_session_file),
                            "claude",  # Current session is Claude
                        )

                        # Should call codex_continue
                        mock_codex.assert_called_once()

    def test_cross_agent_choice_claude(self, mock_session_file):
        """Test choosing Claude when continuing Codex session."""
        with patch(
            "claude_code_tools.session_utils.display_lineage"
        ) as mock_lineage:
            mock_lineage.return_value = ([], mock_session_file)

            with patch(
                "claude_code_tools.session_utils.is_agent_available",
                return_value=True
            ):
                with patch("builtins.input") as mock_input:
                    # User chooses option 2 (cross-agent), then empty custom prompt
                    mock_input.side_effect = ["2", ""]

                    with patch(
                        "claude_code_tools.claude_continue.claude_continue"
                    ) as mock_claude:
                        continue_with_options(
                            str(mock_session_file),
                            "codex",  # Current session is Codex
                        )

                        # Should call claude_continue
                        mock_claude.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
