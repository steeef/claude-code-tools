"""
Comprehensive tests for session resolution functions.

These tests lock in current behavior before refactoring to centralize
all session resolution logic into session_utils.py.

Tests cover all duplicated functions across:
- session_menu_cli.py
- find_claude_session.py
- find_codex_session.py
- export_codex_session.py
- aichat.py
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Import from centralized session_utils module
from claude_code_tools.session_utils import (
    detect_agent_from_path,
    extract_cwd_from_session,
    extract_git_branch_claude,
    find_session_file,
    get_claude_home,
    get_codex_home,
    is_valid_session,
    is_malformed_session,
)


class TestHomeDirectoryResolution:
    """Test get_claude_home() and get_codex_home() with various configurations."""

    def test_get_claude_home_default(self, monkeypatch):
        """Test default Claude home is ~/.claude"""
        monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
        result = get_claude_home(None)
        assert result == Path.home() / ".claude"

    def test_get_claude_home_with_env(self, monkeypatch, tmp_path):
        """Test CLAUDE_CONFIG_DIR environment variable"""
        test_dir = tmp_path / ".claude-test"
        test_dir.mkdir()
        monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(test_dir))
        result = get_claude_home(None)
        assert result == test_dir

    def test_get_claude_home_with_cli_arg(self, monkeypatch, tmp_path):
        """Test CLI argument has highest priority"""
        cli_dir = tmp_path / ".claude-cli"
        env_dir = tmp_path / ".claude-env"
        cli_dir.mkdir()
        env_dir.mkdir()

        monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(env_dir))
        result = get_claude_home(str(cli_dir))
        assert result == cli_dir

    def test_get_claude_home_precedence(self, monkeypatch, tmp_path):
        """Test precedence: CLI > ENV > default"""
        # Test ENV > default
        env_dir = tmp_path / ".claude-env"
        env_dir.mkdir()
        monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(env_dir))
        result = get_claude_home(None)
        assert result == env_dir

        # Test CLI > ENV
        cli_dir = tmp_path / ".claude-cli"
        cli_dir.mkdir()
        result = get_claude_home(str(cli_dir))
        assert result == cli_dir

    def test_get_codex_home_default(self):
        """Test default Codex home is ~/.codex"""
        result = get_codex_home(None)
        assert result == Path.home() / ".codex"

    def test_get_codex_home_with_cli_arg(self, tmp_path):
        """Test CLI argument overrides default"""
        custom_dir = tmp_path / ".codex-custom"
        custom_dir.mkdir()
        result = get_codex_home(str(custom_dir))
        assert result == custom_dir


class TestAgentDetection:
    """Test detect_agent_from_path() for various path patterns."""

    def test_detect_claude_from_standard_path(self):
        """Test detection of Claude from ~/.claude path"""
        path = Path.home() / ".claude" / "projects" / "test" / "session.jsonl"
        result = detect_agent_from_path(path)
        assert result == "claude"

    def test_detect_claude_from_custom_path(self):
        """Test detection of Claude from custom .claude path with subdirectory"""
        # Note: Current implementation only detects "/.claude/" not "/.claude-*/"
        path = Path("/custom/path/.claude/projects/test/session.jsonl")
        result = detect_agent_from_path(path)
        assert result == "claude"

    def test_detect_codex_from_standard_path(self):
        """Test detection of Codex from ~/.codex path"""
        path = Path.home() / ".codex" / "sessions" / "2024" / "11" / "24" / "rollout.jsonl"
        result = detect_agent_from_path(path)
        assert result == "codex"

    def test_detect_codex_from_custom_path(self):
        """Test detection of Codex from custom .codex path"""
        path = Path("/custom/.codex/sessions/2024/11/24/session.jsonl")
        result = detect_agent_from_path(path)
        assert result == "codex"

    def test_detect_agent_returns_none_for_unknown(self):
        """Test returns None for paths without .claude or .codex"""
        path = Path("/random/path/session.jsonl")
        result = detect_agent_from_path(path)
        assert result is None


class TestSessionValidation:
    """Test is_valid_session() whitelist approach."""

    def test_valid_session_with_user_message(self, tmp_path):
        """Test session with user message is valid"""
        session = tmp_path / "valid.jsonl"
        session.write_text(json.dumps({
            "type": "user",
            "sessionId": "test-123",
            "cwd": "/test",
            "message": {"content": "Hello"}
        }) + "\n")
        assert is_valid_session(session)
        assert not is_malformed_session(session)

    def test_valid_session_with_assistant_message(self, tmp_path):
        """Test session with assistant message is valid"""
        session = tmp_path / "valid.jsonl"
        session.write_text(json.dumps({
            "type": "assistant",
            "sessionId": "test-123",
            "cwd": "/test"
        }) + "\n")
        assert is_valid_session(session)

    def test_valid_session_with_tool_result(self, tmp_path):
        """Test session with tool_result is valid"""
        session = tmp_path / "valid.jsonl"
        session.write_text(json.dumps({
            "type": "tool_result",
            "sessionId": "test-123",
            "cwd": "/test"
        }) + "\n")
        assert is_valid_session(session)

    def test_invalid_session_file_history_snapshot(self, tmp_path):
        """Test file-history-snapshot-only session is invalid"""
        session = tmp_path / "invalid.jsonl"
        session.write_text(json.dumps({
            "type": "file-history-snapshot",
            "sessionId": "test-123"
        }) + "\n")
        assert not is_valid_session(session)
        assert is_malformed_session(session)

    def test_invalid_session_queue_operation(self, tmp_path):
        """Test queue-operation-only session is invalid"""
        session = tmp_path / "invalid.jsonl"
        session.write_text(json.dumps({
            "type": "queue-operation",
            "sessionId": "test-123"
        }) + "\n")
        assert not is_valid_session(session)
        assert is_malformed_session(session)

    def test_invalid_session_missing_session_id(self, tmp_path):
        """Test session without sessionId is invalid"""
        session = tmp_path / "invalid.jsonl"
        session.write_text(json.dumps({
            "type": "user",
            "cwd": "/test"
        }) + "\n")
        assert not is_valid_session(session)
        assert is_malformed_session(session)

    def test_invalid_session_empty_file(self, tmp_path):
        """Test empty file is invalid"""
        session = tmp_path / "empty.jsonl"
        session.write_text("")
        assert not is_valid_session(session)
        assert is_malformed_session(session)

    def test_invalid_session_malformed_json(self, tmp_path):
        """Test malformed JSON is invalid"""
        session = tmp_path / "malformed.jsonl"
        session.write_text("not json\n")
        assert not is_valid_session(session)
        assert is_malformed_session(session)

    def test_valid_sub_agent_session(self, tmp_path):
        """Test sub-agent (sidechain) session is valid"""
        session = tmp_path / "agent-abc123.jsonl"
        session.write_text(json.dumps({
            "type": "assistant",
            "sessionId": "test-123",
            "isSidechain": True,
            "agentId": "abc123",
            "cwd": "/test"
        }) + "\n")
        assert is_valid_session(session)


class TestMetadataExtraction:
    """Test extraction of cwd and git branch from sessions."""

    def test_extract_cwd_from_first_line(self, tmp_path):
        """Test extracting cwd when it's in the first line"""
        session = tmp_path / "session.jsonl"
        session.write_text(json.dumps({
            "type": "user",
            "sessionId": "test-123",
            "cwd": "/test/directory"
        }) + "\n")
        result = extract_cwd_from_session(session)
        assert result == "/test/directory"

    def test_extract_cwd_from_later_line(self, tmp_path):
        """Test extracting cwd when it appears after first line"""
        session = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"type": "file-history-snapshot", "sessionId": "test-123"}),
            json.dumps({"type": "file-history-snapshot", "sessionId": "test-123"}),
            json.dumps({"type": "user", "sessionId": "test-123", "cwd": "/test/dir"}),
        ]
        session.write_text("\n".join(lines) + "\n")
        result = extract_cwd_from_session(session)
        assert result == "/test/dir"

    def test_extract_cwd_returns_none_when_missing(self, tmp_path):
        """Test returns None when cwd is not in first 5 lines"""
        session = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"type": "file-history-snapshot", "sessionId": "test-123"})
            for _ in range(6)
        ]
        session.write_text("\n".join(lines) + "\n")
        result = extract_cwd_from_session(session)
        assert result is None

    def test_extract_git_branch_claude(self, tmp_path):
        """Test extracting git branch from Claude session"""
        session = tmp_path / "session.jsonl"
        session.write_text(json.dumps({
            "type": "file-history-snapshot",
            "sessionId": "test-123",
            "metadata": {"git": {"branch": "main"}}
        }) + "\n")
        result = extract_git_branch_claude(session)
        assert result == "main"

    def test_extract_git_branch_returns_none_when_missing(self, tmp_path):
        """Test returns None when git branch is not found"""
        session = tmp_path / "session.jsonl"
        session.write_text(json.dumps({
            "type": "user",
            "sessionId": "test-123",
            "cwd": "/test"
        }) + "\n")
        result = extract_git_branch_claude(session)
        assert result is None


class TestSessionFileLookup:
    """Test find_session_file() with various inputs."""

    def test_find_session_by_full_id(self, tmp_path):
        """Test finding session by full UUID"""
        # Create mock Claude home structure
        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test-project"
        project_dir.mkdir(parents=True)

        session_file = project_dir / "abc123-def456-789.jsonl"
        session_file.write_text(json.dumps({
            "type": "user",
            "sessionId": "abc123-def456-789",
            "cwd": "/test/project"
        }) + "\n")

        result = find_session_file("abc123-def456-789", claude_home=str(claude_home))
        assert result is not None
        agent, path, cwd, branch = result
        assert agent == "claude"
        assert path == session_file
        assert cwd == "/test/project"

    def test_find_session_by_partial_id(self, tmp_path):
        """Test finding session by partial UUID"""
        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test-project"
        project_dir.mkdir(parents=True)

        session_file = project_dir / "abc123-def456-789.jsonl"
        session_file.write_text(json.dumps({
            "type": "user",
            "sessionId": "abc123-def456-789",
            "cwd": "/test/project"
        }) + "\n")

        # Should find with partial ID
        result = find_session_file("abc123", claude_home=str(claude_home))
        assert result is not None
        agent, path, cwd, branch = result
        assert agent == "claude"
        assert "abc123" in path.stem

    def test_find_session_returns_none_for_invalid(self, tmp_path):
        """Test returns None for malformed sessions"""
        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test-project"
        project_dir.mkdir(parents=True)

        # Create file-history-snapshot-only session (invalid)
        session_file = project_dir / "abc123-def456-789.jsonl"
        session_file.write_text(json.dumps({
            "type": "file-history-snapshot",
            "sessionId": "abc123-def456-789"
        }) + "\n")

        # Should not find malformed session
        result = find_session_file("abc123", claude_home=str(claude_home))
        assert result is None

    def test_find_session_skips_sessions_without_cwd(self, tmp_path):
        """Test skips sessions without cwd metadata"""
        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test-project"
        project_dir.mkdir(parents=True)

        # Create session without cwd in first 5 lines
        session_file = project_dir / "abc123-def456-789.jsonl"
        lines = [
            json.dumps({"type": "file-history-snapshot", "sessionId": "abc123"})
            for _ in range(6)
        ]
        session_file.write_text("\n".join(lines) + "\n")

        result = find_session_file("abc123", claude_home=str(claude_home))
        assert result is None

    def test_find_session_searches_codex_when_not_in_claude(self, tmp_path):
        """Test searches Codex home when not found in Claude"""
        # Empty Claude home
        claude_home = tmp_path / ".claude"
        (claude_home / "projects").mkdir(parents=True)

        # Codex session with correct metadata format
        codex_home = tmp_path / ".codex"
        session_dir = codex_home / "sessions" / "2024" / "11" / "24"
        session_dir.mkdir(parents=True)

        session_file = session_dir / "rollout-abc123.jsonl"
        session_file.write_text(json.dumps({
            "type": "session_meta",
            "payload": {
                "id": "abc123-def456-789",
                "cwd": "/test/codex",
                "branch": "main"
            }
        }) + "\n")

        result = find_session_file("abc123", claude_home=str(claude_home), codex_home=str(codex_home))
        assert result is not None
        agent, path, cwd, branch = result
        assert agent == "codex"
        assert "abc123" in path.stem


class TestPathResolution:
    """Test resolve_session_path() (if it exists in current code)."""

    # Note: This function might only exist in session_utils.py or export_codex_session.py
    # Will add tests once we identify all locations
    pass


class TestCommandIntegration:
    """Test actual command flows that use session resolution."""

    def test_find_claude_sessions_real_structure(self, tmp_path, monkeypatch):
        """Test find_sessions() with REAL Claude session structure.

        Real Claude sessions often start with file-history-snapshot (with null sessionId)
        followed by actual user/assistant messages. This test reproduces the bug where
        such sessions are incorrectly marked as malformed.
        """
        # Create mock Claude home structure
        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-Users-test-Git-langroid"
        project_dir.mkdir(parents=True)

        # Create session with REAL structure: file-history-snapshot first (with null sessionId)
        session_file = project_dir / "0b7f882b-0bb3-46b5-88e4-50365c12363c.jsonl"
        lines = [
            # Line 1: file-history-snapshot with NULL sessionId (real Claude behavior)
            json.dumps({
                "type": "file-history-snapshot",
                "sessionId": None,
                "cwd": None
            }),
            # Line 2: First actual user message with real sessionId
            json.dumps({
                "type": "user",
                "sessionId": "0b7f882b-0bb3-46b5-88e4-50365c12363c",
                "cwd": "/Users/test/Git/langroid",
                "message": {"content": "help with langroid"}
            }),
            json.dumps({
                "type": "assistant",
                "sessionId": "0b7f882b-0bb3-46b5-88e4-50365c12363c",
                "cwd": "/Users/test/Git/langroid"
            }),
        ]
        session_file.write_text("\n".join(lines) + "\n")

        # Change to the langroid project directory
        test_project = tmp_path / "Users" / "test" / "Git" / "langroid"
        test_project.mkdir(parents=True)
        monkeypatch.chdir(str(test_project))

        # Import and call find_sessions
        from claude_code_tools.find_claude_session import find_sessions

        # This should find the session (no keywords = match all)
        # Note: Use global_search=True because local search would require
        # the directory name to match the full converted path including temp dir
        results = find_sessions(
            keywords=[],
            global_search=True,  # Search all projects
            claude_home=str(claude_home),
            no_sub=True,  # Exclude sub-agents (like user did)
        )

        # Should find 1 session
        assert len(results) == 1, f"Expected 1 session, found {len(results)}"
        session_id = results[0][0]
        assert session_id == "0b7f882b-0bb3-46b5-88e4-50365c12363c"

    def test_find_claude_sessions_with_keywords(self, tmp_path, monkeypatch):
        """Test find_sessions() command flow with keyword search.

        This tests the full flow: find_sessions() -> search_keywords_in_file()
        which was broken when search_keywords_in_file() was accidentally removed.
        """
        # Create mock Claude home structure
        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test-project"
        project_dir.mkdir(parents=True)

        # Create a valid session with searchable content
        # NOTE: First line must be a valid message type (user/assistant/tool_result)
        # to pass validation. file-history-snapshot alone makes session invalid.
        session_file = project_dir / "abc123-def456.jsonl"
        lines = [
            json.dumps({
                "type": "user",
                "sessionId": "abc123-def456",
                "cwd": "/test/project",
                "message": {"content": "fix the authentication bug"}
            }),
            json.dumps({
                "type": "file-history-snapshot",
                "sessionId": "abc123-def456",
                "metadata": {"git": {"branch": "main"}}
            }),
            json.dumps({
                "type": "assistant",
                "sessionId": "abc123-def456",
                "cwd": "/test/project"
            }),
        ]
        session_file.write_text("\n".join(lines) + "\n")

        # Create and change to a project directory
        test_project = tmp_path / "test-project"
        test_project.mkdir()
        monkeypatch.chdir(str(test_project))

        # Import and call find_sessions (this will fail if search_keywords_in_file is missing)
        from claude_code_tools.find_claude_session import find_sessions

        # This should find the session with keyword "authentication"
        results = find_sessions(
            keywords=["authentication"],
            global_search=True,
            claude_home=str(claude_home),
        )

        # Should find 1 session
        assert len(results) == 1
        session_id, mod_time, create_time, line_count, project_name, preview, cwd, git_branch, is_trimmed, is_sidechain = results[0]
        assert session_id == "abc123-def456"
        assert cwd == "/test/project"
        # Note: git_branch extraction from search_keywords_in_file looks for 'gitBranch' field
        # but actual Claude sessions store it as metadata.git.branch, which is extracted
        # separately by extract_git_branch_claude(). For this test, we just verify the
        # session is found - git_branch extraction is tested separately in TestMetadataExtraction.


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
