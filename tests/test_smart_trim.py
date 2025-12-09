"""Tests for smart-trim with real session files using CLI-based analysis.

These tests make actual CLI calls to Claude/Codex.
Run with: pytest -xvs tests/test_smart_trim.py
"""

import shutil
import tempfile
from pathlib import Path
import pytest


class TestSmartTrim:
    """Tests using real session files and CLI-based analysis."""

    @pytest.fixture
    def real_claude_session_file(self):
        """Copy a real 505-line Claude session file for testing."""
        source = Path(
            "/Users/pchalasani/.claude/projects/-Users-pchalasani-Git-"
            "claude-code-tools/fcbfa69d-ffc7-4c74-a5f0-9ddb4c063939.jsonl"
        )

        if not source.exists():
            pytest.skip(f"Real Claude session file not found: {source}")

        # Copy to temp location
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.jsonl', delete=False
        ) as f:
            temp_path = Path(f.name)

        shutil.copy(source, temp_path)
        yield temp_path

        # Cleanup
        temp_path.unlink(missing_ok=True)

    @pytest.fixture
    def real_codex_session_file(self):
        """Copy a real 632-line Codex session file for testing."""
        source = Path(
            "/Users/pchalasani/.codex/sessions/2025/09/16/"
            "rollout-2025-09-16T13-32-29-b13ef1f9-c977-4172-a7e4-bb364706b796.jsonl"
        )

        if not source.exists():
            pytest.skip(f"Real Codex session file not found: {source}")

        # Copy to temp location
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.jsonl', delete=False
        ) as f:
            temp_path = Path(f.name)

        shutil.copy(source, temp_path)
        yield temp_path

        # Cleanup
        temp_path.unlink(missing_ok=True)

    def test_cli_analysis_on_claude_session(self, real_claude_session_file):
        """Test CLI-based analysis on a Claude session."""
        from claude_code_tools.smart_trim_core import identify_trimmable_lines_cli

        print(f"\n📄 Analyzing Claude session file: {real_claude_session_file}")
        print(f"   File has {sum(1 for _ in open(real_claude_session_file))} lines")
        print(f"   Using CLI with parallel sub-agents...\n")

        # Run the analysis
        trimmable = identify_trimmable_lines_cli(
            real_claude_session_file,
            exclude_types=["user"],
            preserve_recent=10,
            cli_type="claude",
        )

        print(f"\n✅ Analysis complete!")
        print(f"   Found {len(trimmable)} trimmable lines")

        # Verify results - CLI returns list of (line_idx, rationale, summary) tuples
        assert isinstance(trimmable, list)

        if len(trimmable) > 0:
            # Should be tuples with 3 elements
            assert all(isinstance(item, tuple) for item in trimmable)
            assert all(len(item) == 3 for item in trimmable)

            # Extract indices for validation
            indices = [item[0] for item in trimmable]
            print(f"   Trimmable indices (first 20): {indices[:20]}")

            # All indices should be valid
            total_lines = sum(1 for _ in open(real_claude_session_file))
            assert all(0 <= idx < total_lines for idx in indices)

            # Verify no duplicates
            assert len(indices) == len(set(indices))

    def test_cli_analysis_on_codex_session(self, real_codex_session_file):
        """Test CLI-based analysis on a Codex session."""
        from claude_code_tools.smart_trim_core import identify_trimmable_lines_cli

        print(f"\n📄 Analyzing Codex session file: {real_codex_session_file}")
        print(f"   File has {sum(1 for _ in open(real_codex_session_file))} lines")
        print(f"   Using CLI...\n")

        # Run the analysis (use claude CLI even for codex sessions - it works on both)
        trimmable = identify_trimmable_lines_cli(
            real_codex_session_file,
            exclude_types=["user"],
            preserve_recent=10,
            cli_type="claude",
        )

        print(f"\n✅ Analysis complete!")
        print(f"   Found {len(trimmable)} trimmable lines")

        # Verify results - CLI returns list of (line_idx, rationale, summary) tuples
        assert isinstance(trimmable, list)

        if len(trimmable) > 0:
            # Should be tuples with 3 elements
            assert all(isinstance(item, tuple) for item in trimmable)
            assert all(len(item) == 3 for item in trimmable)

            # Extract indices for validation
            indices = [item[0] for item in trimmable]
            print(f"   Trimmable indices (first 20): {indices[:20]}")

            # All indices should be valid
            total_lines = sum(1 for _ in open(real_codex_session_file))
            assert all(0 <= idx < total_lines for idx in indices)

            # Verify no duplicates
            assert len(indices) == len(set(indices))

    def test_full_smart_trim_workflow(self, real_claude_session_file):
        """Test the complete smart-trim workflow: analyze + trim + verify."""
        from claude_code_tools.smart_trim_core import identify_trimmable_lines_cli
        from claude_code_tools.smart_trim import trim_lines

        # Step 1: Identify trimmable lines
        print(f"\n🔍 Step 1: Analyzing session with CLI...")
        trimmable = identify_trimmable_lines_cli(
            real_claude_session_file,
            cli_type="claude",
        )

        print(f"   Identified {len(trimmable)} trimmable lines")

        if len(trimmable) == 0:
            print("   No lines to trim - skipping trim step")
            return

        # Extract line indices from tuples
        line_indices = [item[0] for item in trimmable]

        # Step 2: Trim the session
        print(f"\n✂️  Step 2: Trimming session...")
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.jsonl', delete=False
        ) as f:
            output_file = Path(f.name)

        try:
            stats = trim_lines(real_claude_session_file, line_indices, output_file)

            print(f"   Lines trimmed: {stats['num_lines_trimmed']}")
            print(f"   Characters saved: {stats['chars_saved']:,}")
            print(f"   Tokens saved (est): ~{stats['tokens_saved']:,}")

            # Step 3: Verify trimmed file
            print(f"\n✅ Step 3: Verifying trimmed session...")

            original_lines = sum(1 for _ in open(real_claude_session_file))
            trimmed_lines = sum(1 for _ in open(output_file))

            assert trimmed_lines == original_lines, (
                "Trimmed file should have same number of lines"
            )
            # Note: num_lines_trimmed may be less than len(trimmable) if some
            # lines are too short for truncation to save space
            assert stats['num_lines_trimmed'] <= len(trimmable)

            print(f"   ✓ Trimmed file has {trimmed_lines} lines (same as original)")
            print(f"   ✓ {stats['num_lines_trimmed']} lines actually trimmed")

        finally:
            output_file.unlink(missing_ok=True)

    def test_cli_returns_rationales(self, real_claude_session_file):
        """Test that CLI analysis returns rationales for each trimmable line."""
        from claude_code_tools.smart_trim_core import identify_trimmable_lines_cli

        print(f"\n📄 Analyzing session with CLI (always returns rationales)...")
        trimmable = identify_trimmable_lines_cli(
            real_claude_session_file,
            preserve_recent=5,
            cli_type="claude",
        )

        print(f"\n✅ Analysis complete!")
        print(f"   Found {len(trimmable)} trimmable lines with rationales")

        # Verify results
        assert isinstance(trimmable, list)

        if len(trimmable) > 0:
            # Should be list of tuples with 3 elements
            assert all(isinstance(item, tuple) for item in trimmable)
            assert all(len(item) == 3 for item in trimmable)

            # First element is int, second and third are strings
            print(f"\n   Sample rationales (first 10):")
            for line_idx, rationale, summary in trimmable[:10]:
                assert isinstance(line_idx, int)
                assert isinstance(rationale, str)
                assert isinstance(summary, str)
                print(f"   Line {line_idx}: {rationale}")
                if summary:
                    print(f"      → {summary}")
