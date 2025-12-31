"""Tests for command_utils functions."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add hooks directory to path for import
hooks_dir = Path(__file__).parent.parent / "plugins" / "safety-hooks" / "hooks"
sys.path.insert(0, str(hooks_dir))

from command_utils import extract_subcommands, expand_alias, expand_command_aliases
import command_utils


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


# Mock alias cache for testing (avoids slow shell startup)
MOCK_ALIASES = {
    "gco": "git checkout",
    "gcam": "git commit -a -m",
    "gs": "git status",
    "ll": "ls -la",
}


class TestExpandAlias:
    """Tests for expand_alias function."""

    @pytest.fixture(autouse=True)
    def mock_alias_cache(self):
        """Mock the alias cache to avoid shell startup."""
        with patch.object(command_utils, "_alias_cache", MOCK_ALIASES):
            yield

    def test_expands_known_alias(self):
        """Expands a known alias."""
        assert expand_alias("gco -b feature") == "git checkout -b feature"

    def test_expands_alias_with_args(self):
        """Expands alias and preserves arguments."""
        assert expand_alias('gcam "commit message"') == 'git commit -a -m "commit message"'

    def test_no_expansion_for_unknown(self):
        """Unknown commands are returned unchanged."""
        assert expand_alias("unknown_cmd arg1") == "unknown_cmd arg1"

    def test_skip_git_command(self):
        """git command is not expanded (already known)."""
        assert expand_alias("git checkout -f") == "git checkout -f"

    def test_skip_rm_command(self):
        """rm command is not expanded (already known)."""
        assert expand_alias("rm -rf foo") == "rm -rf foo"

    def test_skip_path_command(self):
        """Commands with paths are not expanded."""
        assert expand_alias("/usr/bin/git status") == "/usr/bin/git status"

    def test_empty_command(self):
        """Empty command returns empty."""
        assert expand_alias("") == ""

    def test_alias_only_no_args(self):
        """Alias with no arguments."""
        assert expand_alias("gs") == "git status"


class TestExpandCommandAliases:
    """Tests for expand_command_aliases function."""

    @pytest.fixture(autouse=True)
    def mock_alias_cache(self):
        """Mock the alias cache to avoid shell startup."""
        with patch.object(command_utils, "_alias_cache", MOCK_ALIASES):
            yield

    def test_expands_single_alias(self):
        """Expands alias in single command."""
        assert expand_command_aliases("gco -f") == "git checkout -f"

    def test_expands_compound_command(self):
        """Expands aliases in compound command with &&."""
        result = expand_command_aliases('gco -f && gcam "msg"')
        assert result == 'git checkout -f && git commit -a -m "msg"'

    def test_preserves_operators(self):
        """Preserves && || ; operators."""
        result = expand_command_aliases("gs && gco main || ll")
        assert result == "git status && git checkout main || ls -la"

    def test_mixed_alias_and_regular(self):
        """Handles mix of aliases and regular commands."""
        result = expand_command_aliases("cd /tmp && gco main")
        assert result == "cd /tmp && git checkout main"

    def test_empty_command(self):
        """Empty command returns empty."""
        assert expand_command_aliases("") == ""

    def test_semicolon_separator(self):
        """Handles semicolon separated commands."""
        result = expand_command_aliases("gs; gco main")
        assert result == "git status; git checkout main"
