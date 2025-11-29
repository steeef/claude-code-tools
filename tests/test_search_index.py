"""Tests for Tantivy search index."""

import json
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def sample_exports(tmp_path: Path) -> Path:
    """Create sample exported sessions with YAML front matter."""
    exports_dir = tmp_path / "exports"
    claude_dir = exports_dir / "claude"
    claude_dir.mkdir(parents=True)

    # Create 3 sample exports
    sessions = [
        {
            "session_id": "session-abc123",
            "agent": "claude",
            "project": "my-project",
            "branch": "main",
            "cwd": "/Users/test/my-project",
            "lines": 50,
            "modified": "2025-11-28T10:00:00",
            "content": "User asked about Python decorators and how to use them.",
        },
        {
            "session_id": "session-def456",
            "agent": "claude",
            "project": "my-project",
            "branch": "feature",
            "cwd": "/Users/test/my-project",
            "lines": 100,
            "modified": "2025-11-29T08:00:00",
            "content": "Discussion about TypeScript interfaces and type safety.",
        },
        {
            "session_id": "session-ghi789",
            "agent": "claude",
            "project": "other-project",
            "branch": "main",
            "cwd": "/Users/test/other-project",
            "lines": 30,
            "modified": "2025-11-27T12:00:00",
            "content": "Help with Rust borrow checker errors and lifetime issues.",
        },
    ]

    for session in sessions:
        content = session.pop("content")
        export_file = claude_dir / f"{session['session_id']}.txt"

        yaml_str = yaml.dump(session, default_flow_style=False)
        with open(export_file, "w") as f:
            f.write(f"---\n{yaml_str}---\n\n")
            f.write(f"> {content}\n")

    return exports_dir


@pytest.fixture
def index_path(tmp_path: Path) -> Path:
    """Return path for test index."""
    return tmp_path / "test-index"


class TestSearchIndex:
    """Tests for SessionIndex class."""

    def test_build_index_creates_index_directory(
        self, sample_exports: Path, index_path: Path
    ):
        """Should create index at specified path."""
        from claude_code_tools.search_index import SessionIndex

        index = SessionIndex(index_path)
        index.build_from_exports(sample_exports)

        assert index_path.exists()
        # Tantivy creates meta.json file
        assert (index_path / "meta.json").exists()

    def test_build_index_indexes_documents(
        self, sample_exports: Path, index_path: Path
    ):
        """Should index all exported sessions."""
        from claude_code_tools.search_index import SessionIndex

        index = SessionIndex(index_path)
        stats = index.build_from_exports(sample_exports)

        assert stats["indexed"] == 3

    def test_search_returns_matching_sessions(
        self, sample_exports: Path, index_path: Path
    ):
        """Search query should return sessions with matching content."""
        from claude_code_tools.search_index import SessionIndex

        index = SessionIndex(index_path)
        index.build_from_exports(sample_exports)

        results = index.search("Python decorators")
        assert len(results) >= 1
        # First result should be the Python session
        assert "abc123" in results[0]["session_id"]

    def test_search_returns_snippets(self, sample_exports: Path, index_path: Path):
        """Results should include snippet with match context."""
        from claude_code_tools.search_index import SessionIndex

        index = SessionIndex(index_path)
        index.build_from_exports(sample_exports)

        results = index.search("TypeScript")
        assert len(results) >= 1
        assert "snippet" in results[0]
        assert "TypeScript" in results[0]["snippet"]

    def test_search_returns_metadata(self, sample_exports: Path, index_path: Path):
        """Results should include session metadata."""
        from claude_code_tools.search_index import SessionIndex

        index = SessionIndex(index_path)
        index.build_from_exports(sample_exports)

        results = index.search("Rust")
        assert len(results) >= 1

        result = results[0]
        assert "session_id" in result
        assert "agent" in result
        assert "project" in result
        assert "modified" in result

    def test_search_empty_query_returns_recent(
        self, sample_exports: Path, index_path: Path
    ):
        """Empty query should return recent sessions."""
        from claude_code_tools.search_index import SessionIndex

        index = SessionIndex(index_path)
        index.build_from_exports(sample_exports)

        results = index.get_recent(limit=10)
        assert len(results) == 3

        # Should be sorted by recency (most recent first)
        # session-def456 is most recent (2025-11-29)
        assert "def456" in results[0]["session_id"]

    def test_search_respects_limit(self, sample_exports: Path, index_path: Path):
        """Should respect result limit."""
        from claude_code_tools.search_index import SessionIndex

        index = SessionIndex(index_path)
        index.build_from_exports(sample_exports)

        # Search for something that matches multiple sessions
        results = index.search("help", limit=1)
        assert len(results) == 1

    def test_search_filters_by_project(self, sample_exports: Path, index_path: Path):
        """Should support filtering by project/cwd."""
        from claude_code_tools.search_index import SessionIndex

        index = SessionIndex(index_path)
        index.build_from_exports(sample_exports)

        # Search with project filter
        results = index.search("", project="other-project")

        # Should only return sessions from other-project
        assert len(results) >= 1
        assert all("other-project" in r["project"] for r in results)

    def test_incremental_index_updates(self, sample_exports: Path, index_path: Path):
        """Incremental indexing should only add new/modified files."""
        from claude_code_tools.search_index import SessionIndex

        index = SessionIndex(index_path)

        # First build
        stats1 = index.build_from_exports(sample_exports)
        assert stats1["indexed"] == 3

        # Second build (no changes)
        stats2 = index.build_from_exports(sample_exports)
        assert stats2["indexed"] == 0
        assert stats2["skipped"] == 3

    def test_index_persists_across_instances(
        self, sample_exports: Path, index_path: Path
    ):
        """Index should persist and be usable by new instance."""
        from claude_code_tools.search_index import SessionIndex

        # Build index
        index1 = SessionIndex(index_path)
        index1.build_from_exports(sample_exports)

        # Create new instance and search
        index2 = SessionIndex(index_path)
        results = index2.search("Python")

        assert len(results) >= 1

    def test_search_result_has_score(self, sample_exports: Path, index_path: Path):
        """Search results should include relevance score."""
        from claude_code_tools.search_index import SessionIndex

        index = SessionIndex(index_path)
        index.build_from_exports(sample_exports)

        results = index.search("decorators")
        assert len(results) >= 1
        assert "score" in results[0]
        assert isinstance(results[0]["score"], float)
