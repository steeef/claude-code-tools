"""Tests for export with YAML front matter."""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
import yaml


# We'll import from the module once it exists
# from claude_code_tools.export_session import (
#     export_with_yaml_frontmatter,
#     extract_yaml_frontmatter,
#     parse_exported_session,
# )


@pytest.fixture
def sample_claude_session(tmp_path: Path) -> Path:
    """Create a sample Claude session JSONL file."""
    session_file = tmp_path / "test-session-abc123.jsonl"

    # Typical Claude session structure
    lines = [
        {
            "type": "user",
            "sessionId": "abc123-def456-789",
            "cwd": "/Users/test/project",
            "message": {"role": "user", "content": "Hello, help me with Python"},
        },
        {
            "type": "assistant",
            "sessionId": "abc123-def456-789",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "I'd be happy to help!"}],
            },
        },
        {
            "type": "user",
            "sessionId": "abc123-def456-789",
            "message": {"role": "user", "content": "Thanks!"},
        },
    ]

    with open(session_file, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    return session_file


@pytest.fixture
def sample_trimmed_session(tmp_path: Path) -> Path:
    """Create a sample trimmed session with trim_metadata."""
    session_file = tmp_path / "trimmed-session-xyz789.jsonl"

    lines = [
        {
            "type": "user",
            "sessionId": "xyz789",
            "cwd": "/Users/test/project",
            "trim_metadata": {
                "parent_file": "/path/to/parent.jsonl",
                "trimmed_at": "2025-11-28T10:30:00Z",
                "trim_params": {"threshold": 500},
                "stats": {
                    "num_tools_trimmed": 5,
                    "num_assistant_trimmed": 2,
                    "tokens_saved": 1500,
                },
            },
            "message": {"role": "user", "content": "Continue from where we left"},
        },
    ]

    with open(session_file, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    return session_file


@pytest.fixture
def sample_continued_session(tmp_path: Path) -> Path:
    """Create a sample continued session with continue_metadata."""
    session_file = tmp_path / "continued-session-cont123.jsonl"

    lines = [
        {
            "type": "user",
            "sessionId": "cont123",
            "cwd": "/Users/test/project",
            "continue_metadata": {
                "parent_session_id": "original456",
                "parent_session_file": "/path/to/original.jsonl",
                "exported_chat_log": "exported.txt",
                "continued_at": "2025-11-28T12:00:00Z",
            },
            "message": {"role": "user", "content": "Continuing the work"},
        },
    ]

    with open(session_file, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    return session_file


class TestYAMLFrontMatter:
    """Tests for YAML front matter in exports."""

    def test_export_has_yaml_front_matter(self, sample_claude_session: Path):
        """Export should have --- delimited YAML at top."""
        from claude_code_tools.export_session import export_with_yaml_frontmatter

        output_path = sample_claude_session.parent / "exported.txt"
        export_with_yaml_frontmatter(
            sample_claude_session, output_path, agent="claude"
        )

        content = output_path.read_text()

        # Should start with YAML delimiter
        assert content.startswith("---\n"), "Export should start with YAML delimiter"

        # Should have closing delimiter
        assert "\n---\n" in content, "Export should have closing YAML delimiter"

    def test_yaml_contains_session_id(self, sample_claude_session: Path):
        """YAML must include session_id."""
        from claude_code_tools.export_session import export_with_yaml_frontmatter

        output_path = sample_claude_session.parent / "exported.txt"
        export_with_yaml_frontmatter(
            sample_claude_session, output_path, agent="claude"
        )

        content = output_path.read_text()
        yaml_content = extract_yaml_from_export(content)

        assert "session_id" in yaml_content
        assert yaml_content["session_id"] is not None

    def test_yaml_contains_agent(self, sample_claude_session: Path):
        """YAML must include agent type."""
        from claude_code_tools.export_session import export_with_yaml_frontmatter

        output_path = sample_claude_session.parent / "exported.txt"
        export_with_yaml_frontmatter(
            sample_claude_session, output_path, agent="claude"
        )

        content = output_path.read_text()
        yaml_content = extract_yaml_from_export(content)

        assert yaml_content["agent"] == "claude"

    def test_yaml_contains_metadata(self, sample_claude_session: Path):
        """YAML must include basic metadata: cwd, lines, created, modified."""
        from claude_code_tools.export_session import export_with_yaml_frontmatter

        output_path = sample_claude_session.parent / "exported.txt"
        export_with_yaml_frontmatter(
            sample_claude_session, output_path, agent="claude"
        )

        content = output_path.read_text()
        yaml_content = extract_yaml_from_export(content)

        # Check required fields exist
        assert "cwd" in yaml_content
        assert "lines" in yaml_content
        assert "modified" in yaml_content
        assert "file_path" in yaml_content

    def test_yaml_contains_lineage_for_trimmed(self, sample_trimmed_session: Path):
        """Trimmed sessions should have lineage info in YAML."""
        from claude_code_tools.export_session import export_with_yaml_frontmatter

        output_path = sample_trimmed_session.parent / "exported.txt"
        export_with_yaml_frontmatter(
            sample_trimmed_session, output_path, agent="claude"
        )

        content = output_path.read_text()
        yaml_content = extract_yaml_from_export(content)

        assert yaml_content.get("derivation_type") == "trimmed"
        assert "parent_session_file" in yaml_content

    def test_yaml_trim_stats_for_trimmed_sessions(self, sample_trimmed_session: Path):
        """Trimmed sessions should have trim_stats in YAML."""
        from claude_code_tools.export_session import export_with_yaml_frontmatter

        output_path = sample_trimmed_session.parent / "exported.txt"
        export_with_yaml_frontmatter(
            sample_trimmed_session, output_path, agent="claude"
        )

        content = output_path.read_text()
        yaml_content = extract_yaml_from_export(content)

        assert "trim_stats" in yaml_content
        trim_stats = yaml_content["trim_stats"]
        assert "tokens_saved" in trim_stats
        assert trim_stats["tokens_saved"] == 1500

    def test_yaml_contains_lineage_for_continued(self, sample_continued_session: Path):
        """Continued sessions should have lineage info in YAML."""
        from claude_code_tools.export_session import export_with_yaml_frontmatter

        output_path = sample_continued_session.parent / "exported.txt"
        export_with_yaml_frontmatter(
            sample_continued_session, output_path, agent="claude"
        )

        content = output_path.read_text()
        yaml_content = extract_yaml_from_export(content)

        assert yaml_content.get("derivation_type") == "continued"
        assert "parent_session_id" in yaml_content
        assert yaml_content["parent_session_id"] == "original456"

    def test_export_content_after_yaml(self, sample_claude_session: Path):
        """Actual conversation content follows YAML front matter."""
        from claude_code_tools.export_session import export_with_yaml_frontmatter

        output_path = sample_claude_session.parent / "exported.txt"
        export_with_yaml_frontmatter(
            sample_claude_session, output_path, agent="claude"
        )

        content = output_path.read_text()

        # Split on closing delimiter
        parts = content.split("\n---\n", 1)
        assert len(parts) == 2, "Should have YAML and content sections"

        conversation = parts[1]
        # Should contain user message
        assert "Hello, help me with Python" in conversation
        # Should contain assistant response
        assert "I'd be happy to help" in conversation

    def test_yaml_is_valid_parseable(self, sample_claude_session: Path):
        """YAML front matter should be valid and parseable."""
        from claude_code_tools.export_session import export_with_yaml_frontmatter

        output_path = sample_claude_session.parent / "exported.txt"
        export_with_yaml_frontmatter(
            sample_claude_session, output_path, agent="claude"
        )

        content = output_path.read_text()
        yaml_content = extract_yaml_from_export(content)

        # Should not raise and should return dict
        assert isinstance(yaml_content, dict)


def extract_yaml_from_export(content: str) -> dict:
    """Helper to extract and parse YAML from exported content."""
    if not content.startswith("---\n"):
        raise ValueError("Content does not start with YAML delimiter")

    # Find closing delimiter
    end_idx = content.find("\n---\n", 4)
    if end_idx == -1:
        raise ValueError("No closing YAML delimiter found")

    yaml_str = content[4:end_idx]
    return yaml.safe_load(yaml_str)
