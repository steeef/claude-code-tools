"""Tests for smart-trim with real session files and parallel agents.

These tests make actual API calls to Claude Agent SDK.
Run with: pytest -xvs tests/test_smart_trim.py
"""

import shutil
import tempfile
from pathlib import Path
import pytest


class TestSmartTrim:
    """Tests using real session files and Claude Agent SDK."""

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

    def test_parallel_agents_on_claude_session(self, real_claude_session_file):
        """Test that parallel agents analyze all chunks of a Claude session."""
        from claude_code_tools.smart_trim_core import (
            identify_trimmable_lines
        )

        # Use small chunk size to force multiple agents
        max_lines_per_agent = 50

        print(f"\n📄 Analyzing Claude session file: {real_claude_session_file}")
        print(f"   File has {sum(1 for _ in open(real_claude_session_file))} lines")
        print(f"   Using max_lines_per_agent={max_lines_per_agent}")
        print(f"   This will launch multiple parallel agents...\n")

        # Run the analysis
        trimmable = identify_trimmable_lines(
            real_claude_session_file,
            exclude_types=["user"],
            preserve_recent=10,
            max_lines_per_agent=max_lines_per_agent
        )

        print(f"\n✅ Analysis complete!")
        print(f"   Found {len(trimmable)} trimmable lines")
        print(f"   Trimmable indices (first 20): {trimmable[:20]}")

        # Verify results
        assert isinstance(trimmable, list)
        assert all(isinstance(idx, int) for idx in trimmable)

        # Should find at least some trimmable content in a 505-line session
        assert len(trimmable) > 0, "Should identify some trimmable lines"

        # All indices should be valid
        total_lines = sum(1 for _ in open(real_claude_session_file))
        assert all(0 <= idx < total_lines for idx in trimmable)

        # Verify no duplicates
        assert len(trimmable) == len(set(trimmable))

        # Should be sorted
        assert trimmable == sorted(trimmable)

    def test_parallel_agents_on_codex_session(self, real_codex_session_file):
        """Test that parallel agents analyze all chunks of a Codex session."""
        from claude_code_tools.smart_trim_core import (
            identify_trimmable_lines
        )

        # Use small chunk size to force multiple agents
        max_lines_per_agent = 75

        print(f"\n📄 Analyzing Codex session file: {real_codex_session_file}")
        print(f"   File has {sum(1 for _ in open(real_codex_session_file))} lines")
        print(f"   Using max_lines_per_agent={max_lines_per_agent}")
        print(f"   This will launch multiple parallel agents...\n")

        # Run the analysis
        trimmable = identify_trimmable_lines(
            real_codex_session_file,
            exclude_types=["user"],
            preserve_recent=10,
            max_lines_per_agent=max_lines_per_agent
        )

        print(f"\n✅ Analysis complete!")
        print(f"   Found {len(trimmable)} trimmable lines")
        print(f"   Trimmable indices (first 20): {trimmable[:20]}")

        # Verify results
        assert isinstance(trimmable, list)
        assert all(isinstance(idx, int) for idx in trimmable)

        # Should find at least some trimmable content in a 632-line session
        assert len(trimmable) > 0, "Should identify some trimmable lines"

        # All indices should be valid
        total_lines = sum(1 for _ in open(real_codex_session_file))
        assert all(0 <= idx < total_lines for idx in trimmable)

        # Verify no duplicates
        assert len(trimmable) == len(set(trimmable))

        # Should be sorted
        assert trimmable == sorted(trimmable)

    def test_full_smart_trim_workflow(self, real_claude_session_file):
        """Test the complete smart-trim workflow: analyze + trim + verify."""
        from claude_code_tools.smart_trim_core import (
            identify_trimmable_lines
        )
        from claude_code_tools.smart_trim import trim_lines

        # Step 1: Identify trimmable lines
        print(f"\n🔍 Step 1: Analyzing session with parallel agents...")
        trimmable = identify_trimmable_lines(
            real_claude_session_file,
            max_lines_per_agent=100  # Will create ~5 parallel agents
        )

        print(f"   Identified {len(trimmable)} trimmable lines")

        # Step 2: Trim the session
        print(f"\n✂️  Step 2: Trimming session...")
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.jsonl', delete=False
        ) as f:
            output_file = Path(f.name)

        try:
            stats = trim_lines(real_claude_session_file, trimmable, output_file)

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
            assert stats['num_lines_trimmed'] == len(trimmable)
            assert stats['chars_saved'] > 0, "Should save some characters"

            # Verify placeholders exist
            with open(output_file) as f:
                content = f.read()
                assert '"trimmed_line": true' in content

            print(f"   ✓ Trimmed file has {trimmed_lines} lines (same as original)")
            print(f"   ✓ Placeholders inserted correctly")
            print(f"   ✓ Character savings verified")

        finally:
            output_file.unlink(missing_ok=True)

    def test_configurable_chunk_size(self, real_claude_session_file):
        """Test that different chunk sizes work correctly."""
        from claude_code_tools.smart_trim_core import (
            identify_trimmable_lines
        )

        # Test with different chunk sizes
        for chunk_size in [25, 50, 100, 200]:
            print(f"\n🧪 Testing with chunk_size={chunk_size}...")

            trimmable = identify_trimmable_lines(
                real_claude_session_file,
                max_lines_per_agent=chunk_size,
                preserve_recent=5
            )

            total_lines = sum(1 for _ in open(real_claude_session_file))
            expected_chunks = (total_lines - 5) // chunk_size + 1

            print(f"   Found {len(trimmable)} trimmable lines")
            print(f"   Expected ~{expected_chunks} parallel agents")

            assert isinstance(trimmable, list)
            assert len(trimmable) >= 0

    def test_verbose_mode_with_rationales(self, real_claude_session_file):
        """Test verbose mode returns rationales for each trimmable line."""
        from claude_code_tools.smart_trim_core import (
            identify_trimmable_lines
        )

        print(f"\n📄 Analyzing session in VERBOSE mode...")
        trimmable = identify_trimmable_lines(
            real_claude_session_file,
            max_lines_per_agent=50,
            verbose=True
        )

        print(f"\n✅ Analysis complete!")
        print(f"   Found {len(trimmable)} trimmable lines with rationales")

        # Verify results
        assert isinstance(trimmable, list)

        if len(trimmable) > 0:
            # Should be list of tuples
            assert all(isinstance(item, tuple) for item in trimmable)
            assert all(len(item) == 2 for item in trimmable)

            # First element should be int, second should be string
            print(f"\n   Sample rationales (first 10):")
            for line_idx, rationale in trimmable[:10]:
                assert isinstance(line_idx, int)
                assert isinstance(rationale, str)
                assert len(rationale) > 0
                print(f"   Line {line_idx}: {rationale}")

            # Verify sorted by line index
            indices = [item[0] for item in trimmable]
            assert indices == sorted(indices)
