"""Tests for export-all command."""

import json
import time
from pathlib import Path

import pytest


@pytest.fixture
def mock_claude_home(tmp_path: Path) -> Path:
    """Create a mock Claude home directory with sessions."""
    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects" / "-Users-test-project"
    projects_dir.mkdir(parents=True)

    # Create sample sessions
    for i in range(3):
        session_file = projects_dir / f"session-{i}.jsonl"
        lines = [
            {
                "type": "user",
                "sessionId": f"session-{i}",
                "cwd": "/Users/test/project",
                "message": {"role": "user", "content": f"Message {i}"},
            },
        ]
        with open(session_file, "w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")

    return claude_home


@pytest.fixture
def mock_codex_home(tmp_path: Path) -> Path:
    """Create a mock Codex home directory with sessions."""
    codex_home = tmp_path / ".codex"
    sessions_dir = codex_home / "sessions" / "2025" / "11" / "28"
    sessions_dir.mkdir(parents=True)

    # Create sample Codex session
    session_file = sessions_dir / "rollout-codex-session.jsonl"
    lines = [
        {
            "type": "session_meta",
            "payload": {"cwd": "/Users/test/project", "git": {"branch": "main"}},
        },
        {
            "type": "response_item",
            "item": {
                "role": "user",
                "content": [{"type": "input_text", "text": "Hello from Codex"}],
            },
        },
    ]
    with open(session_file, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    return codex_home


class TestExportAll:
    """Tests for export_all_sessions function."""

    def test_export_all_creates_output_directory(
        self, mock_claude_home: Path, tmp_path: Path
    ):
        """Should create export directory if not exists."""
        from claude_code_tools.export_all import export_all_sessions

        output_dir = tmp_path / "exports"
        assert not output_dir.exists()

        export_all_sessions(
            output_dir=output_dir,
            claude_home=mock_claude_home,
            codex_home=tmp_path / ".codex",  # Non-existent
        )

        assert output_dir.exists()

    def test_export_all_exports_claude_sessions(
        self, mock_claude_home: Path, tmp_path: Path
    ):
        """Should export all Claude sessions."""
        from claude_code_tools.export_all import export_all_sessions

        output_dir = tmp_path / "exports"
        stats = export_all_sessions(
            output_dir=output_dir,
            claude_home=mock_claude_home,
            codex_home=tmp_path / ".codex",
        )

        # Should have exported 3 sessions
        assert stats["exported"] >= 3

        # Check export files exist
        claude_exports = output_dir / "claude"
        assert claude_exports.exists()
        exported_files = list(claude_exports.glob("*.txt"))
        assert len(exported_files) == 3

    def test_export_all_exports_codex_sessions(
        self, mock_codex_home: Path, tmp_path: Path
    ):
        """Should export Codex sessions."""
        from claude_code_tools.export_all import export_all_sessions

        output_dir = tmp_path / "exports"
        stats = export_all_sessions(
            output_dir=output_dir,
            claude_home=tmp_path / ".claude",  # Non-existent
            codex_home=mock_codex_home,
        )

        # Should have exported 1 Codex session
        assert stats["exported"] >= 1

        # Check export files exist
        codex_exports = output_dir / "codex"
        assert codex_exports.exists()

    def test_export_all_skips_already_exported(
        self, mock_claude_home: Path, tmp_path: Path
    ):
        """Should skip sessions with up-to-date exports (by mtime)."""
        from claude_code_tools.export_all import export_all_sessions

        output_dir = tmp_path / "exports"

        # First export
        stats1 = export_all_sessions(
            output_dir=output_dir,
            claude_home=mock_claude_home,
            codex_home=tmp_path / ".codex",
        )
        assert stats1["exported"] == 3
        assert stats1["skipped"] == 0

        # Second export - should skip all
        stats2 = export_all_sessions(
            output_dir=output_dir,
            claude_home=mock_claude_home,
            codex_home=tmp_path / ".codex",
        )
        assert stats2["exported"] == 0
        assert stats2["skipped"] == 3

    def test_export_all_force_reexports(self, mock_claude_home: Path, tmp_path: Path):
        """--force should re-export even if up-to-date."""
        from claude_code_tools.export_all import export_all_sessions

        output_dir = tmp_path / "exports"

        # First export
        export_all_sessions(
            output_dir=output_dir,
            claude_home=mock_claude_home,
            codex_home=tmp_path / ".codex",
        )

        # Force re-export
        stats = export_all_sessions(
            output_dir=output_dir,
            claude_home=mock_claude_home,
            codex_home=tmp_path / ".codex",
            force=True,
        )
        assert stats["exported"] == 3
        assert stats["skipped"] == 0

    def test_export_all_returns_stats(self, mock_claude_home: Path, tmp_path: Path):
        """Should return count of exported, skipped, failed."""
        from claude_code_tools.export_all import export_all_sessions

        output_dir = tmp_path / "exports"
        stats = export_all_sessions(
            output_dir=output_dir,
            claude_home=mock_claude_home,
            codex_home=tmp_path / ".codex",
        )

        assert "exported" in stats
        assert "skipped" in stats
        assert "failed" in stats
        assert isinstance(stats["exported"], int)
        assert isinstance(stats["skipped"], int)
        assert isinstance(stats["failed"], int)

    def test_export_all_exports_have_yaml_frontmatter(
        self, mock_claude_home: Path, tmp_path: Path
    ):
        """Exported files should have YAML front matter."""
        from claude_code_tools.export_all import export_all_sessions

        output_dir = tmp_path / "exports"
        export_all_sessions(
            output_dir=output_dir,
            claude_home=mock_claude_home,
            codex_home=tmp_path / ".codex",
        )

        # Check first export file
        claude_exports = output_dir / "claude"
        exported_files = list(claude_exports.glob("*.txt"))
        assert len(exported_files) > 0

        content = exported_files[0].read_text()
        assert content.startswith("---\n"), "Export should have YAML front matter"
        assert "\n---\n" in content, "Export should have closing YAML delimiter"

    def test_export_all_reexports_modified_sessions(
        self, mock_claude_home: Path, tmp_path: Path
    ):
        """Should re-export sessions that have been modified since last export."""
        from claude_code_tools.export_all import export_all_sessions

        output_dir = tmp_path / "exports"

        # First export
        export_all_sessions(
            output_dir=output_dir,
            claude_home=mock_claude_home,
            codex_home=tmp_path / ".codex",
        )

        # Modify one session file
        time.sleep(0.1)  # Ensure mtime difference
        projects_dir = mock_claude_home / "projects" / "-Users-test-project"
        session_file = projects_dir / "session-0.jsonl"
        with open(session_file, "a") as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": "session-0",
                        "message": {"role": "user", "content": "New message"},
                    }
                )
                + "\n"
            )

        # Second export - should re-export the modified one
        stats = export_all_sessions(
            output_dir=output_dir,
            claude_home=mock_claude_home,
            codex_home=tmp_path / ".codex",
        )
        assert stats["exported"] == 1
        assert stats["skipped"] == 2
