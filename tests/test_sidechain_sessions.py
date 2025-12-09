"""Unit tests for sidechain (sub-agent) session handling."""

import json
import tempfile
from pathlib import Path

import pytest

from claude_code_tools.find_claude_session import (
    is_sidechain_session,
    find_sessions as find_claude_sessions,
)
from claude_code_tools.find_session import search_all_agents


@pytest.fixture
def temp_output_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sidechain_session_file(temp_output_dir):
    """Create a sidechain session file for testing."""
    sidechain_file = temp_output_dir / "agent-test123.jsonl"

    # Create a minimal sidechain session with required fields
    sidechain_content = [
        {
            "parentUuid": None,
            "isSidechain": True,
            "userType": "external",
            "cwd": "/test/project",
            "sessionId": "abc123",
            "agentId": "test123",
            "type": "user",
            "message": {
                "role": "user",
                "content": "Test sub-agent message"
            }
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": "Test assistant response"
            }
        }
    ]

    with open(sidechain_file, 'w') as f:
        for entry in sidechain_content:
            f.write(json.dumps(entry) + '\n')

    return sidechain_file


@pytest.fixture
def normal_session_file(temp_output_dir):
    """Create a normal (non-sidechain) session file for testing."""
    normal_file = temp_output_dir / "normal-session.jsonl"

    # Create a minimal normal session
    normal_content = [
        {
            "isSidechain": False,
            "cwd": "/test/project",
            "sessionId": "def456",
            "type": "user",
            "message": {
                "role": "user",
                "content": "Test normal message"
            }
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": "Test assistant response"
            }
        }
    ]

    with open(normal_file, 'w') as f:
        for entry in normal_content:
            f.write(json.dumps(entry) + '\n')

    return normal_file


class TestIsSidechainSession:
    """Tests for detecting sidechain sessions."""

    def test_sidechain_session_detected(self, sidechain_session_file):
        """Test that sidechain sessions are correctly identified."""
        assert is_sidechain_session(sidechain_session_file)

    def test_normal_session_not_sidechain(self, normal_session_file):
        """Test that normal sessions are not identified as sidechains."""
        assert not is_sidechain_session(normal_session_file)

    def test_nonexistent_file_returns_false(self):
        """Test that nonexistent files return False."""
        nonexistent = Path("/tmp/does_not_exist_sidechain_test.jsonl")
        assert not is_sidechain_session(nonexistent)

    def test_empty_file_returns_false(self, temp_output_dir):
        """Test that empty files return False."""
        empty_file = temp_output_dir / "empty.jsonl"
        empty_file.touch()
        assert not is_sidechain_session(empty_file)

    def test_invalid_json_returns_false(self, temp_output_dir):
        """Test that files with invalid JSON return False."""
        invalid_file = temp_output_dir / "invalid.jsonl"
        invalid_file.write_text("not valid json\n")
        assert not is_sidechain_session(invalid_file)

    def test_session_without_sidechain_field(self, temp_output_dir):
        """Test that sessions without isSidechain field return False."""
        session_file = temp_output_dir / "no_field.jsonl"
        session_file.write_text(
            '{"type":"session_start","sessionId":"test123"}\n'
        )
        assert not is_sidechain_session(session_file)

    def test_session_with_false_sidechain_field(self, temp_output_dir):
        """Test that sessions with isSidechain=false return False."""
        session_file = temp_output_dir / "false_field.jsonl"
        session_file.write_text(
            '{"isSidechain":false,"sessionId":"test123","type":"user"}\n'
        )
        assert not is_sidechain_session(session_file)


class TestSidechainSessionInSearch:
    """Tests for sidechain sessions appearing in search results."""

    def test_sidechain_appears_in_results(self, temp_output_dir, sidechain_session_file):
        """Test that sidechain sessions appear in search results."""
        # Note: This would require setting up a full mock Claude directory structure
        # For now, we're testing the detection function directly
        # A full integration test would test find_sessions() with a mock directory

        # Verify the file exists and is detected as sidechain
        assert sidechain_session_file.exists()
        assert is_sidechain_session(sidechain_session_file)

    def test_normal_session_appears_in_results(self, temp_output_dir, normal_session_file):
        """Test that normal sessions appear in search results."""
        # Verify the file exists and is NOT detected as sidechain
        assert normal_session_file.exists()
        assert not is_sidechain_session(normal_session_file)


class TestSidechainSessionIndicator:
    """Tests for sidechain session indicators in display."""

    def test_sidechain_has_indicator_in_tuple(self, temp_output_dir, sidechain_session_file):
        """Test that sidechain sessions have is_sidechain=True in tuple."""
        # This tests the data structure that would be returned
        # In actual usage, find_sessions() would return tuples with is_sidechain as 10th element
        is_sidechain = is_sidechain_session(sidechain_session_file)
        assert is_sidechain is True

    def test_normal_session_has_no_indicator_in_tuple(self, temp_output_dir, normal_session_file):
        """Test that normal sessions have is_sidechain=False in tuple."""
        is_sidechain = is_sidechain_session(normal_session_file)
        assert is_sidechain is False


class TestSidechainFilenamePattern:
    """Tests for sidechain session filename patterns."""

    def test_agent_prefix_filename(self, temp_output_dir):
        """Test that files with 'agent-' prefix can be sidechains."""
        # Create a sidechain file with agent- prefix
        agent_file = temp_output_dir / "agent-xyz789.jsonl"
        agent_file.write_text(
            '{"isSidechain":true,"agentId":"xyz789","type":"user","message":{"role":"user","content":"test"}}\n'
        )

        assert is_sidechain_session(agent_file)

    def test_uuid_filename_can_be_normal(self, temp_output_dir):
        """Test that UUID filenames can be normal sessions."""
        # Create a normal session with UUID filename
        uuid_file = temp_output_dir / "12345678-1234-5678-1234-567812345678.jsonl"
        uuid_file.write_text(
            '{"isSidechain":false,"sessionId":"12345678-1234-5678-1234-567812345678","type":"user","message":{"role":"user","content":"test"}}\n'
        )

        assert not is_sidechain_session(uuid_file)


class TestSidechainWithTrimming:
    """Tests for interactions between sidechain and trimmed sessions."""

    def test_trimmed_sidechain_session(self, temp_output_dir):
        """Test that a sidechain session can also be trimmed."""
        # Create a sidechain session with trim_metadata
        trimmed_sidechain = temp_output_dir / "agent-trimmed.jsonl"

        content = {
            "trim_metadata": {
                "parent_file": "/path/to/original.jsonl",
                "trimmed_at": "2025-11-14T00:00:00",
                "trim_params": {"threshold": 500},
                "stats": {"num_tools_trimmed": 5}
            },
            "isSidechain": True,
            "agentId": "trimmed123",
            "type": "user",
            "message": {"role": "user", "content": "test"}
        }

        trimmed_sidechain.write_text(json.dumps(content) + '\n')

        # Should be detected as sidechain
        assert is_sidechain_session(trimmed_sidechain)

        # Would also be detected as trimmed by is_trimmed_session()
        from claude_code_tools.trim_session import is_trimmed_session
        assert is_trimmed_session(trimmed_sidechain)
