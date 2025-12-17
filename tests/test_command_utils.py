"""Tests for command_utils.extract_subcommands."""
import sys
from pathlib import Path

import pytest

# Add hooks directory to path for import
hooks_dir = Path(__file__).parent.parent / "plugins" / "safety-hooks" / "hooks"
sys.path.insert(0, str(hooks_dir))

from command_utils import extract_subcommands


class TestExtractSubcommands:
    """Tests for extract_subcommands function."""

    def test_single_command(self):
        """Single command returns list with one element."""
        assert extract_subcommands("git add .") == ["git add ."]

    def test_empty_string(self):
        """Empty string returns empty list."""
        assert extract_subcommands("") == []

    def test_none_like_empty(self):
        """None-like values return empty list."""
        assert extract_subcommands(None) == []

    def test_split_on_and(self):
        """Splits on && operator."""
        result = extract_subcommands("cd /tmp && git commit -m 'msg'")
        assert result == ["cd /tmp", "git commit -m 'msg'"]

    def test_split_on_or(self):
        """Splits on || operator."""
        result = extract_subcommands("git pull || echo 'failed'")
        assert result == ["git pull", "echo 'failed'"]

    def test_split_on_semicolon(self):
        """Splits on ; operator."""
        result = extract_subcommands("ls; pwd; whoami")
        assert result == ["ls", "pwd", "whoami"]

    def test_mixed_operators(self):
        """Handles mixed operators."""
        result = extract_subcommands("a && b || c ; d")
        assert result == ["a", "b", "c", "d"]

    def test_triple_command_chain(self):
        """Handles chain of three commands."""
        result = extract_subcommands("cd /tmp && git add . && git commit -m 'x'")
        assert result == ["cd /tmp", "git add .", "git commit -m 'x'"]

    def test_whitespace_handling(self):
        """Strips extra whitespace around operators and commands."""
        result = extract_subcommands("  cmd1   &&   cmd2  ")
        assert result == ["cmd1", "cmd2"]

    def test_preserves_internal_spaces(self):
        """Preserves spaces within commands."""
        result = extract_subcommands("git commit -m 'hello world'")
        assert result == ["git commit -m 'hello world'"]

    def test_empty_segments_filtered(self):
        """Empty segments from splitting are filtered out."""
        result = extract_subcommands("cmd1 && && cmd2")
        assert result == ["cmd1", "cmd2"]
